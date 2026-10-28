"""Regression tests for ChunkingService.

The chunker used to rebuild chunks by concatenating split pieces and only
re-attached separators that were punctuation, so newline and space separators
vanished: line-wrapped PDF text came out as "structural volume andthe reserve
density", and char_start/char_end drifted away from the source text. These
tests pin the properties that bug broke.
"""

import random
import re

import pytest

from advandeb_kb.services.chunking_service import ChunkingService

# Line-wrapped, hyphenated, double-spaced text in the shape pdftotext emits.
PDF_LIKE = (
    "Abstract\n\n"
    "The standard DEB model distinguishes structural volume and\n"
    "the reserve density of an individual. Growth is fuelled by reserve\n"
    "mobilisation, and the kappa-rule allocates a fixed fraction of the\n"
    "mobilisation flux to somatic maintenance plus growth; the rest goes\n"
    "to maturation or reproduction. Experimental evidence points to\n"
    "developmental processes being heterochronic (McKinney and\n"
    "McNamara, 1991). The digestion efficiency for Tetramin was around\n"
    "0.5,  growth  efficiency was just 0.7 and the value for\tthe allocation\n"
    "fraction to soma (0.44) was close to the one that maximizes ultimate\n"
    "reproduction.\n\n\n\n"
    "1. Introduction\n"
    "Theoretical progress in the analysis of these processes lags behind\n"
    "experimental work for lack of a quantifier for internal time which does\n"
    "not necessarily correlate with morphological (e.g. length) or chronolog-\n"
    "ical (e.g. age) criteria. We focus on zebrafish Danio rerio since it is\n"
    "widely used to study development.\n"
) * 3


def _words(text: str) -> list[str]:
    return text.split()


def _is_contiguous_subsequence(needle: list[str], haystack: list[str]) -> bool:
    n = len(needle)
    first = needle[0]
    for i, w in enumerate(haystack):
        if w == first and haystack[i:i + n] == needle:
            return True
    return False


@pytest.fixture
def svc():
    return ChunkingService(chunk_size=200, overlap=50, min_chunk=10)


def test_line_wrapped_text_keeps_word_boundaries(svc):
    chunks = svc.chunk_document(PDF_LIKE, "doc")
    assert len(chunks) > 3
    joined = " ".join(c.text for c in chunks)
    for glued in ("andthe", "reservemobilisation", "beingheterochronic", "behindexperimental"):
        assert glued not in joined
    source_words = _words(PDF_LIKE)
    for c in chunks:
        # Every chunk is a run of whole source words, in source order.
        assert _is_contiguous_subsequence(_words(c.text), source_words), c.text


def test_offsets_round_trip_to_source(svc):
    chunks = svc.chunk_document(PDF_LIKE, "doc")
    for c in chunks:
        assert ChunkingService.normalize(PDF_LIKE[c.char_start:c.char_end]) == c.text
    starts = [c.char_start for c in chunks]
    assert starts == sorted(starts)
    assert chunks[-1].char_end <= len(PDF_LIKE)


def test_offsets_are_exact_slices_of_normalized_source(svc):
    source = ChunkingService.normalize(PDF_LIKE)
    for c in svc.chunk_document(source, "doc"):
        assert source[c.char_start:c.char_end] == c.text


def test_no_source_text_is_lost(svc):
    source = ChunkingService.normalize(PDF_LIKE)
    covered = bytearray(len(source))
    for c in svc.chunk_document(source, "doc"):
        covered[c.char_start:c.char_end] = b"\x01" * (c.char_end - c.char_start)
    missing = [i for i, ch in enumerate(source) if not ch.isspace() and not covered[i]]
    assert missing == [], source[missing[0]:missing[0] + 40] if missing else ""


def test_word_level_fallback_does_not_concatenate_words():
    # One long line: no paragraph, line or sentence separators to split on,
    # so the splitter must fall back to word boundaries.
    words = [f"word{i}" for i in range(300)]
    text = " ".join(words)
    svc = ChunkingService(chunk_size=100, overlap=20, min_chunk=5)
    chunks = svc.chunk_document(text, "doc")
    assert len(chunks) > 5
    for c in chunks:
        assert re.fullmatch(r"word\d+( word\d+)*", c.text), c.text
        assert text[c.char_start:c.char_end] == c.text


def test_chunk_length_is_bounded(svc):
    for c in svc.chunk_document(PDF_LIKE, "doc"):
        assert len(c.text) <= svc.chunk_size + svc.overlap + svc.min_chunk


def test_overlap_starts_on_a_word_boundary(svc):
    chunks = svc.chunk_document(PDF_LIKE, "doc")
    source_words = set(_words(PDF_LIKE))
    for prev, cur in zip(chunks, chunks[1:]):
        assert cur.char_start < prev.char_end, "consecutive chunks should overlap"
        assert _words(cur.text)[0] in source_words


def test_ligatures_are_expanded_and_offsets_still_round_trip():
    text = "The digestion efﬁciency for zebra ﬁsh was 0.5 and the ﬂux was high. " * 20
    svc = ChunkingService(chunk_size=120, overlap=30, min_chunk=5)
    chunks = svc.chunk_document(text, "doc")
    assert chunks
    for c in chunks:
        assert "ﬁ" not in c.text and "ﬂ" not in c.text
        assert ChunkingService.normalize(text[c.char_start:c.char_end]) == c.text
    assert "zebra fish" in chunks[0].text


def test_unbroken_run_is_hard_split():
    text = "x" * 1000
    svc = ChunkingService(chunk_size=300, overlap=0, min_chunk=5)
    chunks = svc.chunk_document(text, "doc")
    assert [len(c.text) for c in chunks] == [300, 300, 300, 100]
    assert "".join(c.text for c in chunks) == text


def test_short_heading_is_not_dropped():
    text = "Results\n\n" + ("Growth was measured at three temperatures. " * 12)
    svc = ChunkingService(chunk_size=200, overlap=0, min_chunk=30)
    chunks = svc.chunk_document(text, "doc")
    assert chunks[0].text.startswith("Results")


def test_randomised_round_trip():
    rng = random.Random(7)
    vocab = ["energy", "reserve", "structure", "kappa", "growth", "maturity",
             "(Kooijman,", "2010).", "e.g.", "0.44", "ﬁsh", "volume"]
    seps = [" ", " ", " ", " ", "\n", "\n\n", "  ", "\t", ". ", "\n\n\n\n"]
    for _ in range(25):
        text = "".join(rng.choice(vocab) + rng.choice(seps) for _ in range(rng.randint(50, 400)))
        svc = ChunkingService(chunk_size=rng.choice([64, 128, 256]), overlap=rng.choice([0, 16, 40]), min_chunk=5)
        norm_words = _words(ChunkingService.normalize(text))
        for c in svc.chunk_document(text, "doc"):
            assert ChunkingService.normalize(text[c.char_start:c.char_end]) == c.text
            assert _is_contiguous_subsequence(_words(c.text), norm_words)
