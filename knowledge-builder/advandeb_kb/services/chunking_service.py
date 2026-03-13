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
"""

from __future__ import annotations

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
        text = self._normalize(text)
        if not text:
            return []

        raw_chunks = self._split(text, self.separators)
        chunks_with_overlap = self._apply_overlap(raw_chunks)

        result: list[Chunk] = []
        cursor = 0
        for i, chunk_text in enumerate(chunks_with_overlap):
            if len(chunk_text) < self.min_chunk:
                continue
            # Find char_start by scanning forward from cursor
            start = text.find(chunk_text[:20], cursor)
            if start == -1:
                start = cursor
            end = start + len(chunk_text)
            result.append(
                Chunk(
                    text=chunk_text,
                    document_id=document_id,
                    chunk_index=i,
                    char_start=start,
                    char_end=min(end, len(text)),
                )
            )
            # Advance cursor to overlap point for next chunk
            cursor = max(cursor, end - self.overlap)

        # Re-index sequentially after filtering short chunks
        for idx, chunk in enumerate(result):
            chunk.chunk_index = idx

        return result

    def chunk_text(self, text: str) -> list[str]:
        """Simple variant — returns plain strings (no metadata)."""
        text = self._normalize(text)
        if not text:
            return []
        raw = self._split(text, self.separators)
        return [c for c in self._apply_overlap(raw) if len(c) >= self.min_chunk]

    # ------------------------------------------------------------------
    # Internal splitting logic
    # ------------------------------------------------------------------

    def _normalize(self, text: str) -> str:
        """Clean up whitespace without destroying paragraph structure."""
        # Collapse runs of blank lines to a single blank line
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Collapse runs of spaces/tabs on a line
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    def _split(self, text: str, separators: list[str]) -> list[str]:
        """
        Recursively split text using the first separator that produces
        pieces smaller than chunk_size. Falls back to the next separator
        if pieces are still too large.
        """
        if not separators:
            # Final fallback: hard split by character count
            return [text[i: i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]

        separator = separators[0]
        remaining_seps = separators[1:]

        if separator == "":
            # Character-level split
            return [text[i: i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]

        pieces = text.split(separator) if separator else list(text)
        # Re-attach separator to all but last piece (preserves sentence ends etc.)
        if separator.strip():
            # Punctuation separator — keep it at end of previous piece
            joined = []
            for j, p in enumerate(pieces):
                joined.append(p + (separator if j < len(pieces) - 1 else ""))
            pieces = joined

        merged: list[str] = []
        current = ""

        for piece in pieces:
            if not piece:
                continue
            candidate = current + piece if not current else current + piece

            if len(candidate) <= self.chunk_size:
                current = candidate
            else:
                if current:
                    if len(current) > self.chunk_size:
                        # Current is too large — recurse to split it further
                        merged.extend(self._split(current, remaining_seps))
                    else:
                        merged.append(current)
                current = piece

        if current:
            if len(current) > self.chunk_size:
                merged.extend(self._split(current, remaining_seps))
            else:
                merged.append(current)

        return merged

    def _apply_overlap(self, chunks: list[str]) -> list[str]:
        """
        Add overlap between consecutive chunks by prepending the tail of
        the previous chunk to the current one.
        """
        if self.overlap <= 0 or len(chunks) <= 1:
            return chunks

        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-self.overlap:]
            overlapped = prev_tail + chunks[i]
            result.append(overlapped)
        return result
