"""
EvidenceRegistryService — freeze retrieved chunks + graph facts into a
citation registry with stable markers before answer generation.

The registry assigns sequential, stable citation markers ([1], [2], …,
[G1], [G2], …, [SF1], [SF2], …) to all evidence gathered during the
retrieve + graph-enrich phase of the deterministic chat pipeline.

This solves the historical bug where the LLM was expected to cite markers
that were only assigned during prompt construction: if any chunk ordering
changed between retrieval and prompt rendering the markers would not match.

Usage
-----
    registry = EvidenceRegistry.from_retrieval(chunks, graph_result)
    prompt_block = registry.render_observation_block()
    # ... call LLM with prompt_block ...
    citations = registry.extract_citations(llm_answer_text)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from advandeb_kb.models.chat import (
    CitationRef,
    CitationSourceType,
    make_citation_id,
    strip_collection_prefix,
)


@dataclass
class RegistryEntry:
    """One item in the evidence registry."""

    marker: str                  # e.g. "1", "G3", "SF2"
    citation_id: str             # canonical id like "chunk:abc123"
    source_type: CitationSourceType
    document_id: Optional[str]
    chunk_id: Optional[str]
    fact_id: Optional[str]
    stylized_fact_id: Optional[str]
    evidence_text: str           # first 300 chars of content


class EvidenceRegistry:
    """
    Immutable-after-build registry that maps stable markers to evidence items.

    Build once from the retrieval results; then:
      - render_observation_block()   → observation text injected into LLM prompt
      - extract_citations(text)      → list[CitationRef] from inline markers
    """

    def __init__(self) -> None:
        self._entries: list[RegistryEntry] = []
        # Lookup maps for O(1) access
        self._by_marker: dict[str, RegistryEntry] = {}
        self._by_citation_id: dict[str, RegistryEntry] = {}

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_retrieval(
        cls,
        chunks: list[dict],
        graph_result: Optional[dict] = None,
    ) -> "EvidenceRegistry":
        """
        Build a registry from hybrid_search chunks and expand_context result.

        Text chunks get plain numeric markers [1], [2], …
        Graph facts get   [G1], [G2], …
        Stylized facts get [SF1], [SF2], …
        """
        reg = cls()
        chunk_n = 0
        graph_n = 0
        sf_n = 0

        for chunk in chunks:
            # Skip synthetic graph chunks that will be added from graph_result
            meta = chunk.get("metadata", {})
            source = meta.get("source", "chunk")
            if source in ("fact", "stylized_fact"):
                continue

            chunk_n += 1
            marker = str(chunk_n)
            doc_id = (
                chunk.get("document_id")
                or meta.get("document_id")
                or ""
            )
            raw_id = (
                chunk.get("chunk_id")
                or chunk.get("id")
                or chunk.get("_key")
                or ""
            )
            chunk_id = strip_collection_prefix(str(raw_id))
            citation_id = make_citation_id("chunk", chunk_id)
            text = (chunk.get("text") or "")[:300]

            entry = RegistryEntry(
                marker=marker,
                citation_id=citation_id,
                source_type="chunk",
                document_id=doc_id or None,
                chunk_id=chunk_id or None,
                fact_id=None,
                stylized_fact_id=None,
                evidence_text=text,
            )
            reg._add(entry)

        # Graph facts
        for fact in (graph_result or {}).get("facts", [])[:8]:
            graph_n += 1
            marker = f"G{graph_n}"
            raw_id = (
                fact.get("_key")
                or fact.get("_id")
                or fact.get("id")
                or f"gfact_{graph_n}"
            )
            fact_id = strip_collection_prefix(str(raw_id))
            citation_id = make_citation_id("fact", fact_id)
            doc_id = str(fact.get("document_id") or "")
            text = (fact.get("content") or "")[:300]

            entry = RegistryEntry(
                marker=marker,
                citation_id=citation_id,
                source_type="fact",
                document_id=doc_id or None,
                chunk_id=None,
                fact_id=fact_id or None,
                stylized_fact_id=None,
                evidence_text=text,
            )
            reg._add(entry)

        # Stylized facts
        for sf in (graph_result or {}).get("stylized_facts", [])[:5]:
            sf_n += 1
            marker = f"SF{sf_n}"
            raw_id = (
                sf.get("_key")
                or sf.get("_id")
                or sf.get("id")
                or f"gsf_{sf_n}"
            )
            sf_id = strip_collection_prefix(str(raw_id))
            citation_id = make_citation_id("stylized_fact", sf_id)
            doc_id = str(sf.get("document_id") or "")
            text = (sf.get("statement") or "")[:300]

            entry = RegistryEntry(
                marker=marker,
                citation_id=citation_id,
                source_type="stylized_fact",
                document_id=doc_id or None,
                chunk_id=None,
                fact_id=None,
                stylized_fact_id=sf_id or None,
                evidence_text=text,
            )
            reg._add(entry)

        return reg

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def entries(self) -> list[RegistryEntry]:
        return list(self._entries)

    def chunk_count(self) -> int:
        return sum(1 for e in self._entries if e.source_type == "chunk")

    def fact_count(self) -> int:
        return sum(1 for e in self._entries if e.source_type in ("fact", "stylized_fact"))

    # ------------------------------------------------------------------
    # Prompt rendering
    # ------------------------------------------------------------------

    def render_observation_block(self) -> str:
        """
        Render a numbered observation block to inject into the LLM prompt.

        Example output:
            Found 3 relevant text chunk(s):
              [1] [doc:abc123] The phospholipid bilayer consists of…
              [2] [doc:def456] von Bertalanffy growth rate depends on…

            2 knowledge-graph fact(s):
              [G1] Assimilation efficiency for Mytilus edulis is 0.8…
              [G2] κ-rule: fraction of assimilation flux to soma…

            1 stylized fact(s):
              [SF1] Metabolic rate scales with body mass as M^(3/4)…
        """
        lines: list[str] = []

        # Text chunks
        chunk_entries = [e for e in self._entries if e.source_type == "chunk"]
        if chunk_entries:
            lines.append(f"Found {len(chunk_entries)} relevant text chunk(s):")
            for e in chunk_entries:
                doc_tag = f"[doc:{(e.document_id or '?')[:8]}]"
                lines.append(f"  [{e.marker}] {doc_tag} {e.evidence_text}")

        # Graph facts
        fact_entries = [e for e in self._entries if e.source_type == "fact"]
        if fact_entries:
            lines.append(f"\n{len(fact_entries)} knowledge-graph fact(s):")
            for e in fact_entries:
                lines.append(f"  [{e.marker}] {e.evidence_text}")

        # Stylized facts
        sf_entries = [e for e in self._entries if e.source_type == "stylized_fact"]
        if sf_entries:
            lines.append(f"\n{len(sf_entries)} stylized fact(s):")
            for e in sf_entries:
                lines.append(f"  [{e.marker}] {e.evidence_text}")

        return "\n".join(lines) if lines else "No relevant evidence found."

    def render_chunk_list_for_synthesis(self) -> list[dict]:
        """Return synthetic chunk dicts in the shape expected by SynthesisAgent."""
        result = []
        for e in self._entries:
            result.append({
                "chunk_id": e.citation_id,
                "document_id": e.document_id or "",
                "text": e.evidence_text,
                "metadata": {
                    "document_id": e.document_id or "",
                    "source": e.source_type,
                    "fact_id": e.fact_id,
                    "stylized_fact_id": e.stylized_fact_id,
                    "citation_id": e.citation_id,
                    "marker": e.marker,
                },
            })
        return result

    # ------------------------------------------------------------------
    # Citation extraction
    # ------------------------------------------------------------------

    def extract_citations(self, answer_text: str) -> list[CitationRef]:
        """
        Extract inline citation markers from the LLM answer and resolve them
        against the registry.

        Handles [1], [G3], [SF2] markers.  Out-of-registry markers are
        silently skipped (they cannot be attributed to any evidence).
        """
        cited_markers = set(re.findall(r"\[((?:SF|G)?\d+)\]", answer_text))
        citations: list[CitationRef] = []

        for marker in sorted(cited_markers, key=_sort_key):
            entry = self._by_marker.get(marker)
            if entry is None:
                continue  # unknown marker — cannot cite
            citations.append(
                CitationRef(
                    citation_id=entry.citation_id,
                    marker=f"[{marker}]",
                    source_type=entry.source_type,
                    document_id=entry.document_id,
                    chunk_id=entry.chunk_id,
                    fact_id=entry.fact_id,
                    stylized_fact_id=entry.stylized_fact_id,
                    evidence_text=entry.evidence_text,
                )
            )
        return citations

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add(self, entry: RegistryEntry) -> None:
        self._entries.append(entry)
        self._by_marker[entry.marker] = entry
        if entry.citation_id:
            self._by_citation_id[entry.citation_id] = entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sort_key(marker: str) -> tuple[int, int]:
    """Sort order: text chunks first (numeric), then G-facts, then SF-facts."""
    if marker.startswith("SF"):
        return (2, int(marker[2:]))
    if marker.startswith("G"):
        return (1, int(marker[1:]))
    try:
        return (0, int(marker))
    except ValueError:
        return (3, 0)
