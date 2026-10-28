"""
ChunkingService — recursive character-based text splitter.

No external dependencies (no langchain). Splits text by progressively
smaller separators, respects chunk_size limit, and adds overlap to
preserve context across boundaries.

Separator priority (tried in order):
    "\n\n"  — paragraph breaks
    "\n"    — line breaks
    ". "    — sentence ends
    " "     — word boundaries
    ""      — character-level fallback

Every chunk is a contiguous slice of the normalised text, located by offsets
rather than rebuilt from pieces. An earlier version re-joined split pieces and
re-attached a separator only when it was punctuation, so newline and space
separators vanished at every merge: line-wrapped PDF text came out as
"structural volume andthe reserve density", the word-level fallback glued
words together, and char_start/char_end drifted away from the source. Working
on offsets makes that impossible: whatever lay between two pieces in the
source lies between them in the chunk.

Offset contract: char_start/char_end index the text passed to
chunk_document(), and ``ChunkingService.normalize(text[c.char_start:c.char_end])
== c.text``. For text that is already normalised the slice equals c.text.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Chunk:
    """A text chunk with positional and document metadata."""

    text: str
    document_id: str
    chunk_index: int
    char_start: int
    char_end: int
    # Optional: sentence count or section tag for richer retrieval
    metadata: dict = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        return f"{self.document_id}_chunk_{self.chunk_index}"

    def to_chromadb_metadata(self) -> dict:
        return {
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "char_start": self.char_start,
            "char_end": self.char_end,
            **self.metadata,
        }


# Typographic ligatures that PDF extractors emit as single code points. The
# embedding tokenizer does not decompose them (zebra U+FB01 "sh" tokenizes as
# zebra / U+FB01 / ##sh, never as "fish"), so they are expanded the way NFKC
# would expand them.
_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}

# One alternative per normalisation rule; the replacement for each match is
# chosen in _replacement(). Single spaces are deliberately not matched: they
# need no change, and leaving them out keeps the offset map small.
_NORMALIZE_RE = re.compile(
    r"[ \t\r\f\v]{2,}|[\t\r\f\v]"  # horizontal whitespace runs -> one space
    r"|\n{3,}"                    # runs of blank lines -> one blank line
    r"|[\ufb00-\ufb06]"             # ligatures -> their letters
)


def _replacement(match: str) -> str:
    if match[0] == "\n":
        return "\n\n"
    if match[0] in _LIGATURES:
        return _LIGATURES[match[0]]
    return " "


class _OffsetMap:
    """
    Maps positions in normalised text back to positions in the original.

    Normalisation is a sequence of segments, each either copied verbatim
    (positions map linearly) or replaced (the whole replacement maps to the
    whole original run). Storing segments rather than a per-character table
    keeps this cheap for millions of short abstracts.
    """

    __slots__ = ("_norm_starts", "_segments")

    def __init__(self) -> None:
        self._norm_starts: list[int] = []
        # (norm_start, norm_len, orig_start, orig_len, copied)
        self._segments: list[tuple[int, int, int, int, bool]] = []

    def add(self, norm_start: int, norm_len: int, orig_start: int, orig_len: int, copied: bool) -> None:
        if norm_len <= 0:
            return
        self._norm_starts.append(norm_start)
        self._segments.append((norm_start, norm_len, orig_start, orig_len, copied))

    def _segment(self, pos: int) -> tuple[int, int, int, int, bool]:
        return self._segments[bisect.bisect_right(self._norm_starts, pos) - 1]

    def start(self, pos: int) -> int:
        """Original index of the character at normalised position ``pos``."""
        n_start, _, o_start, _, copied = self._segment(pos)
        return o_start + (pos - n_start) if copied else o_start

    def end(self, pos: int) -> int:
        """Original exclusive end for a normalised exclusive end ``pos``."""
        n_start, _, o_start, o_len, copied = self._segment(pos - 1)
        return o_start + (pos - n_start) if copied else o_start + o_len


class ChunkingService:
    """
    Splits documents into overlapping text chunks suitable for embedding.

    Args:
        chunk_size:   Target character count per chunk (default 512).
        overlap:      Characters shared between consecutive chunks (default 128).
        separators:   Ordered list of separator strings tried recursively.
        min_chunk:    Discard chunks shorter than this (avoids empty fragments).
    """

    DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", "; ", " ", ""]

    def __init__(
        self,
        chunk_size: int = 512,
        overlap: int = 128,
        separators: Optional[list[str]] = None,
        min_chunk: int = 30,
    ):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.separators = separators if separators is not None else self.DEFAULT_SEPARATORS
        self.min_chunk = min_chunk

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_document(self, text: str, document_id: str) -> list[Chunk]:
        """
        Split `text` into overlapping chunks and return a list of Chunk objects.
        The `document_id` is embedded in every chunk for traceability.
        """
        norm, offsets = self._normalize_with_offsets(text or "")
        result: list[Chunk] = []
        for start, end in self._chunk_spans(norm):
            result.append(
                Chunk(
                    text=norm[start:end],
                    document_id=document_id,
                    chunk_index=len(result),
                    char_start=offsets.start(start),
                    char_end=offsets.end(end),
                )
            )
        return result

    def chunk_text(self, text: str) -> list[str]:
        """Simple variant — returns plain strings (no metadata)."""
        return [c.text for c in self.chunk_document(text, "")]

    @staticmethod
    def normalize(text: str) -> str:
        """Clean up whitespace without destroying paragraph structure."""
        return _NORMALIZE_RE.sub(lambda m: _replacement(m.group()), text).strip()

    # ------------------------------------------------------------------
    # Normalisation with offset tracking
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_with_offsets(text: str) -> tuple[str, _OffsetMap]:
        """
        normalize(), plus a map from normalised positions to original ones.

        Leading and trailing whitespace is kept here (spans are trimmed later),
        so the result differs from normalize() only by that whitespace.
        """
        out: list[str] = []
        offsets = _OffsetMap()
        norm_pos = 0
        orig_pos = 0
        for m in _NORMALIZE_RE.finditer(text):
            if m.start() > orig_pos:
                n = m.start() - orig_pos
                out.append(text[orig_pos:m.start()])
                offsets.add(norm_pos, n, orig_pos, n, copied=True)
                norm_pos += n
            raw = m.group()
            rep = _replacement(raw)
            offsets.add(norm_pos, len(rep), m.start(), len(raw), copied=False)
            out.append(rep)
            norm_pos += len(rep)
            orig_pos = m.end()
        if orig_pos < len(text):
            n = len(text) - orig_pos
            out.append(text[orig_pos:])
            offsets.add(norm_pos, n, orig_pos, n, copied=True)
        return "".join(out), offsets

    # ------------------------------------------------------------------
    # Span-based splitting
    # ------------------------------------------------------------------

    def _chunk_spans(self, text: str) -> list[tuple[int, int]]:
        """Final chunk spans over ``text``: split, overlapped, filtered."""
        spans = [s for s in (self._trim(text, a, b) for a, b in self._split(text, 0, len(text), self.separators)) if s]
        spans = self._apply_overlap(text, spans)
        return [(a, b) for a, b in spans if b - a >= self.min_chunk]

    @staticmethod
    def _trim(text: str, start: int, end: int) -> Optional[tuple[int, int]]:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        return (start, end) if end > start else None

    def _split(self, text: str, start: int, end: int, separators: list[str]) -> list[tuple[int, int]]:
        """
        Recursively split text[start:end] into spans of at most chunk_size,
        using the first separator that occurs and falling back to finer ones
        for pieces that are still too large.

        Each piece keeps its trailing separator, so adjacent pieces tile the
        range exactly and merging two pieces is just widening a span.
        """
        if end - start <= self.chunk_size:
            return [(start, end)]

        separator = separators[0] if separators else ""
        remaining = separators[1:]

        if separator == "":
            # Character-level split (last resort: a run with no separator).
            return [(i, min(i + self.chunk_size, end)) for i in range(start, end, self.chunk_size)]

        pieces: list[tuple[int, int]] = []
        piece_start = start
        while True:
            hit = text.find(separator, piece_start, end)
            if hit == -1:
                break
            pieces.append((piece_start, hit + len(separator)))
            piece_start = hit + len(separator)
        if piece_start < end:
            pieces.append((piece_start, end))

        if len(pieces) == 1:
            # Separator absent from this range — try the next one.
            return self._split(text, start, end, remaining)

        merged: list[tuple[int, int]] = []
        cur_start, cur_end = pieces[0]
        for p_start, p_end in pieces[1:]:
            if p_end - cur_start <= self.chunk_size or cur_end - cur_start < self.min_chunk:
                # Fits — or the current span is a fragment (a heading, say)
                # that would be dropped on its own: carry it into the next
                # piece and let the recursion split the combined range.
                cur_end = p_end
                continue
            merged.extend(self._emit(text, cur_start, cur_end, remaining))
            cur_start, cur_end = p_start, p_end
        if merged and cur_end - cur_start < self.min_chunk:
            # Trailing fragment: attach it to the previous span.
            merged[-1] = (merged[-1][0], cur_end)
        else:
            merged.extend(self._emit(text, cur_start, cur_end, remaining))
        return merged

    def _emit(self, text: str, start: int, end: int, remaining: list[str]) -> list[tuple[int, int]]:
        if end - start > self.chunk_size:
            return self._split(text, start, end, remaining)
        return [(start, end)]

    def _apply_overlap(self, text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """
        Extend each chunk back by up to ``overlap`` characters into the
        previous one, starting at a word boundary so no chunk opens on half a
        word.
        """
        if self.overlap <= 0 or len(spans) <= 1:
            return spans

        result = [spans[0]]
        for i in range(1, len(spans)):
            start, end = spans[i]
            prev_start = spans[i - 1][0]
            ov = max(prev_start, start - self.overlap)
            if ov < start and ov > 0 and not text[ov - 1].isspace():
                # Mid-word: move forward to the next word start.
                nxt = ov
                while nxt < start and not text[nxt].isspace():
                    nxt += 1
                ov = nxt
            trimmed = self._trim(text, ov, end)
            result.append(trimmed if trimmed else (start, end))
        return result
