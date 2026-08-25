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
    # Optional pre-resolved document metadata (e.g. from get_claim_consensus,
    # which already joins the source document). When present, downstream
    # provenance enrichment is skipped for this entry.
    title: Optional[str] = None
    authors: list = field(default_factory=list)
    year: Optional[int | str] = None
    journal: Optional[str] = None
    doi: Optional[str] = None


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
        # Running counters so markers stay stable and non-colliding across
        # multiple rounds of evidence being added (e.g. agentic tool calls
        # made *after* the initial retrieval).
        self._chunk_n = 0
        self._graph_n = 0
        self._sf_n = 0
        self._doc_n = 0

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
        reg.add_chunks(chunks)
        reg.add_graph_facts((graph_result or {}).get("facts", [])[:8])
        reg.add_stylized_facts((graph_result or {}).get("stylized_facts", [])[:5])
        return reg

    # ------------------------------------------------------------------
    # Incremental additions — used both by the initial retrieval and by
    # agentic tool calls made mid-conversation, so every piece of evidence
    # the LLM ever sees gets a stable, resolvable marker. Each is dedup'd by
    # citation_id: re-adding the same chunk/fact/SF reuses its existing
    # marker instead of minting a new (colliding-looking) one.
    # ------------------------------------------------------------------

    def add_chunks(self, chunks: list[dict]) -> list[RegistryEntry]:
        added: list[RegistryEntry] = []
        for chunk in chunks:
            meta = chunk.get("metadata", {}) or {}
            source = meta.get("source", "chunk")
            if source in ("fact", "stylized_fact"):
                continue

            raw_id = (
                chunk.get("chunk_id")
                or chunk.get("id")
                or chunk.get("_key")
                or ""
            )
            chunk_id = strip_collection_prefix(str(raw_id))
            citation_id = make_citation_id("chunk", chunk_id)

            existing = self._by_citation_id.get(citation_id) if citation_id else None
            if existing is not None:
                added.append(existing)
                continue

            self._chunk_n += 1
            marker = str(self._chunk_n)
            doc_id = chunk.get("document_id") or meta.get("document_id") or ""
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
            self._add(entry)
            added.append(entry)
        return added

    def add_graph_facts(self, facts: list[dict]) -> list[RegistryEntry]:
        added: list[RegistryEntry] = []
        for fact in facts:
            raw_id = (
                fact.get("_key")
                or fact.get("_id")
                or fact.get("id")
                or ""
            )
            fact_id = strip_collection_prefix(str(raw_id)) if raw_id else ""
            citation_id = make_citation_id("fact", fact_id) if fact_id else ""

            existing = self._by_citation_id.get(citation_id) if citation_id else None
            if existing is not None:
                added.append(existing)
                continue

            self._graph_n += 1
            marker = f"G{self._graph_n}"
            if not fact_id:
                fact_id = f"gfact_{self._graph_n}"
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
            self._add(entry)
            added.append(entry)
        return added

    def add_stylized_facts(self, sfs: list[dict]) -> list[RegistryEntry]:
        added: list[RegistryEntry] = []
        for sf in sfs:
            raw_id = (
                sf.get("_key")
                or sf.get("_id")
                or sf.get("id")
                or ""
            )
            sf_id = strip_collection_prefix(str(raw_id)) if raw_id else ""
            citation_id = make_citation_id("stylized_fact", sf_id) if sf_id else ""

            existing = self._by_citation_id.get(citation_id) if citation_id else None
            if existing is not None:
                added.append(existing)
                continue

            self._sf_n += 1
            marker = f"SF{self._sf_n}"
            if not sf_id:
                sf_id = f"gsf_{self._sf_n}"
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
            self._add(entry)
            added.append(entry)
        return added

    def add_consensus_facts(self, rows: list[dict]) -> list[RegistryEntry]:
        """Register get_claim_consensus supporting/opposing facts as citable
        evidence. Each item already carries its joined source document
        (title/authors/year/journal/doi), so that metadata is stored directly
        on the entry and provenance re-lookup is skipped downstream.

        Mirrors the row/supports/opposes slicing that
        ``ByokChatService._tool_result_to_text`` renders to the LLM (top-3
        rows, top-3 supports, top-2 opposes) so the returned entries line up
        1:1, in order, with what the LLM actually sees.
        """
        added: list[RegistryEntry] = []
        for row in rows[:3]:
            items = list((row.get("supports") or [])[:3]) + list((row.get("opposes") or [])[:2])
            for item in items:
                raw_fact_id = item.get("fact_id") or ""
                fact_id = strip_collection_prefix(str(raw_fact_id)) if raw_fact_id else ""
                citation_id = make_citation_id("fact", fact_id) if fact_id else ""

                existing = self._by_citation_id.get(citation_id) if citation_id else None
                if existing is not None:
                    added.append(existing)
                    continue

                self._graph_n += 1
                marker = f"G{self._graph_n}"
                if not fact_id:
                    fact_id = f"gfact_{self._graph_n}"
                    citation_id = make_citation_id("fact", fact_id)
                doc = item.get("document") or {}
                doc_id = str(doc.get("id") or "")
                authors = doc.get("authors") or []
                if isinstance(authors, str):
                    authors = [authors] if authors.strip() else []

                entry = RegistryEntry(
                    marker=marker,
                    citation_id=citation_id,
                    source_type="fact",
                    document_id=doc_id or None,
                    chunk_id=None,
                    fact_id=fact_id or None,
                    stylized_fact_id=None,
                    evidence_text=(item.get("fact") or "")[:300],
                    title=doc.get("title") or None,
                    authors=authors,
                    year=doc.get("year"),
                    journal=doc.get("journal"),
                    doi=doc.get("doi"),
                )
                self._add(entry)
                added.append(entry)
        return added

    def add_platform_docs(self, docs: list[dict]) -> list[RegistryEntry]:
        """Register AdvanDEB's own documentation/tutorial sections (from
        ``PlatformDocsService.search_platform_docs``) as citable evidence, so
        the assistant can answer questions about the platform itself instead
        of guessing from general training knowledge. Title/text are already
        final — no provenance DB lookup is needed for these.
        """
        added: list[RegistryEntry] = []
        for doc in docs:
            doc_id = str(doc.get("id") or "")
            citation_id = make_citation_id("platform_doc", doc_id) if doc_id else ""

            existing = self._by_citation_id.get(citation_id) if citation_id else None
            if existing is not None:
                added.append(existing)
                continue

            self._doc_n += 1
            marker = f"D{self._doc_n}"
            if not doc_id:
                doc_id = f"doc_section_{self._doc_n}"
                citation_id = make_citation_id("platform_doc", doc_id)

            entry = RegistryEntry(
                marker=marker,
                citation_id=citation_id,
                source_type="platform_doc",
                document_id=None,
                chunk_id=None,
                fact_id=None,
                stylized_fact_id=None,
                evidence_text=(doc.get("text") or "")[:300],
                title=doc.get("title") or None,
            )
            self._add(entry)
            added.append(entry)
        return added

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

        # AdvanDEB's own documentation/tutorials (about the platform, not the science)
        doc_entries = [e for e in self._entries if e.source_type == "platform_doc"]
        if doc_entries:
            lines.append(f"\n{len(doc_entries)} AdvanDEB documentation section(s):")
            for e in doc_entries:
                lines.append(f"  [{e.marker}] {e.title}: {e.evidence_text}")

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

        Handles [1], [G3], [SF2], [D1] markers.  Out-of-registry markers are
        silently skipped (they cannot be attributed to any evidence).
        """
        cited_markers = set(re.findall(r"\[((?:SF|G|D)?\d+)\]", answer_text))
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
                    title=entry.title,
                    authors=list(entry.authors),
                    year=entry.year,
                    journal=entry.journal,
                    doi=entry.doi,
                )
            )
        return citations

    def render_new_entries_block(self, entries: list[RegistryEntry]) -> str:
        """Render freshly-added entries (e.g. from a mid-conversation tool
        call) with their real, registry-assigned markers — so the LLM cites
        markers that ``extract_citations`` can actually resolve, instead of
        a locally-restarted numbering that collides with earlier evidence.
        """
        if not entries:
            return "No new results."
        lines = []
        for e in entries:
            if e.source_type == "chunk":
                doc_tag = f"[doc:{(e.document_id or '?')[:8]}]"
                lines.append(f"  [{e.marker}] {doc_tag} {e.evidence_text}")
            elif e.source_type == "platform_doc":
                lines.append(f"  [{e.marker}] {e.title}: {e.evidence_text}")
            else:
                lines.append(f"  [{e.marker}] {e.evidence_text}")
        return "\n".join(lines)

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
    """Sort order: text chunks first (numeric), then G-facts, SF-facts, D-docs."""
    if marker.startswith("SF"):
        return (2, int(marker[2:]))
    if marker.startswith("G"):
        return (1, int(marker[1:]))
    if marker.startswith("D"):
        return (3, int(marker[1:]))
    try:
        return (0, int(marker))
    except ValueError:
        return (4, 0)
