"""
SynthesisAgent — multi-source answer generation agent (port 8083).

Tools exposed via MCP:
    synthesize_answer    — generate a cited answer from chunks + graph context
    attribute_citations  — extract and link [N] citation markers to sources
    summarize_context    — produce a short summary of retrieved context

Run as standalone process:
    python -m advandeb_kb.agents.synthesis_agent
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from advandeb_kb.agents.base_agent import BaseAgent
from advandeb_kb.config.settings import settings
from advandeb_kb.models.provenance import GraphPathStep, ProvenanceTrace

logger = logging.getLogger(__name__)

AGENT_PORT = 8083

# Default model — override via OLLAMA_MODEL env var
_OLLAMA_MODEL = settings.OLLAMA_MODEL


class SynthesisAgent(BaseAgent):
    """
    Agent that synthesizes cited answers from multi-source retrieved context.

    Calls Ollama for:
      - Answer generation with inline [N] citations
      - Citation attribution (mapping markers back to source chunks)
      - Context summarization
    """

    def __init__(self, port: int = AGENT_PORT, host: str = "localhost"):
        super().__init__(name="synthesis_agent", port=port, host=host)
        self._ollama_url = settings.OLLAMA_BASE_URL

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        # Verify Ollama is reachable
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._ollama_url}/api/tags")
                models = [m["name"] for m in resp.json().get("models", [])]
                logger.info("SynthesisAgent: Ollama reachable — models: %s", models[:5])
        except Exception as exc:
            logger.warning("SynthesisAgent: Ollama unreachable (%s) — synthesis will fail.", exc)

    def register_tools(self) -> None:
        self.server.register_tool(
            name="synthesize_answer",
            handler=self._synthesize_answer,
            description=(
                "Generate a cited answer from retrieved chunks and graph context. "
                "Citations are inline [1], [2] markers linked to source chunks."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The original user question"},
                    "chunks": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Retrieved chunk dicts from RetrievalAgent",
                    },
                    "graph_context": {
                        "type": "object",
                        "description": "Graph expansion result from GraphExplorerAgent",
                        "default": {},
                    },
                    "max_tokens": {"type": "integer", "default": 600},
                },
                "required": ["query", "chunks"],
            },
        )
        self.server.register_tool(
            name="attribute_citations",
            handler=self._attribute_citations,
            description=(
                "Extract [N] citation markers from generated text and map each "
                "back to the corresponding source chunk / document."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "answer_text": {"type": "string"},
                    "chunks": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["answer_text", "chunks"],
            },
        )
        self.server.register_tool(
            name="summarize_context",
            handler=self._summarize_context,
            description="Produce a concise summary of retrieved context chunks.",
            input_schema={
                "type": "object",
                "properties": {
                    "chunks": {"type": "array", "items": {"type": "object"}},
                    "max_sentences": {"type": "integer", "default": 5},
                },
                "required": ["chunks"],
            },
        )

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _synthesize_answer(
        self,
        query: str,
        chunks: list[dict],
        graph_context: dict = {},
        max_tokens: int = 600,
    ) -> dict:
        if not chunks:
            return {
                "answer": "No relevant sources were found.",
                "citations": [],
                "provenance": None,
            }

        context_text = self._build_context(chunks, graph_context)
        prompt = (
            f"You are a scientific knowledge assistant for Dynamic Energy Budget (DEB) theory.\n\n"
            f"Based ONLY on the following sources, answer the question.\n"
            f"Cite sources inline as [1], [2], etc. matching the source numbers below.\n"
            f"If you cannot answer from the sources, say so explicitly.\n\n"
            f"Sources:\n{context_text}\n\n"
            f"Question: {query}\n\n"
            f"Answer:"
        )

        answer = await self._ollama_generate(prompt, max_tokens=max_tokens)
        citations = self._extract_citations(answer, chunks)
        provenance = self._build_provenance(query, chunks, graph_context, citations)

        return {
            "answer": answer,
            "citations": citations,
            "provenance": provenance,
            "source_count": len(chunks),
        }

    async def _attribute_citations(
        self, answer_text: str, chunks: list[dict]
    ) -> dict:
        citations = self._extract_citations(answer_text, chunks)
        return {
            "answer_text": answer_text,
            "citation_count": len(citations),
            "citations": citations,
        }

    async def _summarize_context(
        self, chunks: list[dict], max_sentences: int = 5
    ) -> dict:
        if not chunks:
            return {"summary": "", "chunk_count": 0}

        combined = "\n\n".join(
            f"[{i+1}] {c.get('text', '')[:400]}" for i, c in enumerate(chunks[:10])
        )
        prompt = (
            f"Summarize the following scientific text passages in {max_sentences} sentences "
            f"or fewer. Focus on the key biological facts and mechanisms described.\n\n"
            f"{combined}\n\nSummary:"
        )
        summary = await self._ollama_generate(prompt, max_tokens=300)
        return {"summary": summary, "chunk_count": len(chunks)}

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def _build_context(self, chunks: list[dict], graph_context: dict) -> str:
        lines: list[str] = []

        # Primary sources: retrieved chunks
        for i, chunk in enumerate(chunks[:15]):
            text = chunk.get("text", "")
            meta = chunk.get("metadata", {})
            doc_id = meta.get("document_id", "")
            lines.append(f"[{i+1}] (doc:{doc_id[:8]}...) {text[:500]}")

        # Supplementary: related stylized facts from graph
        sfs = graph_context.get("stylized_facts", [])
        if sfs:
            lines.append("\nRelated principles:")
            for sf in sfs[:5]:
                stmt = sf.get("statement", sf.get("text", ""))
                if stmt:
                    lines.append(f"  • {stmt[:200]}")

        return "\n\n".join(lines)

    # ------------------------------------------------------------------
    # Citation extraction
    # ------------------------------------------------------------------

    def _extract_citations(
        self, answer_text: str, chunks: list[dict]
    ) -> list[dict]:
        """
        Parse [N] markers in answer_text and map to source chunks.
        Returns list of citation dicts: {number, chunk_id, document_id, text_snippet}.
        """
        cited_numbers = {int(m) for m in re.findall(r"\[(\d+)\]", answer_text)}
        citations = []
        for num in sorted(cited_numbers):
            idx = num - 1
            if 0 <= idx < len(chunks):
                chunk = chunks[idx]
                meta = chunk.get("metadata", {})
                citations.append({
                    "number": num,
                    "chunk_id": chunk.get("chunk_id", chunk.get("id", "")),
                    "document_id": meta.get("document_id", ""),
                    "text_snippet": chunk.get("text", "")[:200],
                })
        return citations

    # ------------------------------------------------------------------
    # Provenance builder
    # ------------------------------------------------------------------

    def _build_provenance(
        self,
        query: str,
        chunks: list[dict],
        graph_context: dict,
        citations: list[dict],
    ) -> dict:
        """Build a serialisable provenance dict (not stored — caller decides)."""
        return {
            "query": query,
            "chunks_retrieved": [c.get("chunk_id", c.get("id", "")) for c in chunks],
            "documents_cited": list({c["document_id"] for c in citations if c.get("document_id")}),
            "facts_from_graph": len(graph_context.get("facts", [])),
            "taxa_from_graph": len(graph_context.get("taxa", [])),
            "citation_count": len(citations),
        }

    # ------------------------------------------------------------------
    # Ollama helper
    # ------------------------------------------------------------------

    async def _ollama_generate(self, prompt: str, max_tokens: int = 2000) -> str:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self._ollama_url}/api/generate",
                    json={
                        "model": _OLLAMA_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_predict": max_tokens},
                    },
                )
                resp.raise_for_status()
                return resp.json().get("response", "").strip()
        except Exception as exc:
            logger.error("Ollama generate failed: %s", exc)
            return f"[Generation failed: {exc}]"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = SynthesisAgent()
    agent.run()
