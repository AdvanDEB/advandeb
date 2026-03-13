"""
GraphExplorerAgent — knowledge graph traversal agent (port 8082).

Tools exposed via MCP:
    expand_context          — expand retrieval context from seed chunk IDs
    get_citation_chain      — walk citation graph from a document
    find_related_facts      — find facts supporting/opposing a stylized fact
    traverse_graph          — raw AQL graph traversal from any vertex
    find_taxa_for_document  — organisms linked to a document

Run as standalone process:
    python -m advandeb_kb.agents.graph_explorer_agent
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from advandeb_kb.agents.base_agent import BaseAgent
from advandeb_kb.database.arango_client import ArangoDatabase
from advandeb_kb.services.graph_expansion_service import GraphExpansionService

logger = logging.getLogger(__name__)

AGENT_PORT = 8082
_executor = ThreadPoolExecutor(max_workers=4)


class GraphExplorerAgent(BaseAgent):
    """
    Agent specialized in knowledge graph traversal and context expansion.

    Requires ArangoDB running with the advandeb_kb schema.
    Gracefully returns empty results if ArangoDB is unreachable.
    """

    def __init__(self, port: int = AGENT_PORT, host: str = "localhost"):
        super().__init__(name="graph_explorer", port=port, host=host)
        self._arango: Optional[ArangoDatabase] = None
        self._graph_svc: Optional[GraphExpansionService] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        loop = asyncio.get_event_loop()
        try:
            self._arango = ArangoDatabase()
            await loop.run_in_executor(_executor, self._arango.connect)
            self._graph_svc = GraphExpansionService(self._arango)
            logger.info("GraphExplorerAgent: ArangoDB connected — %s", self._arango.stats())
        except Exception as exc:
            logger.warning(
                "GraphExplorerAgent: ArangoDB unavailable (%s) — tools will return empty results.",
                exc,
            )
            self._graph_svc = None

    def register_tools(self) -> None:
        self.server.register_tool(
            name="expand_context",
            handler=self._expand_context,
            description=(
                "Expand retrieval context from seed chunk IDs by traversing "
                "the knowledge graph. Returns related documents, facts, "
                "stylized facts, and taxa."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Chunk IDs from RetrievalAgent results",
                    },
                    "max_hops": {"type": "integer", "default": 2},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["chunk_ids"],
            },
        )
        self.server.register_tool(
            name="get_citation_chain",
            handler=self._get_citation_chain,
            description="Walk the citation graph outward from a document ID.",
            input_schema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "max_depth": {"type": "integer", "default": 5},
                },
                "required": ["document_id"],
            },
        )
        self.server.register_tool(
            name="find_related_facts",
            handler=self._find_related_facts,
            description="Find facts that support or oppose a stylized fact.",
            input_schema={
                "type": "object",
                "properties": {
                    "stylized_fact_id": {"type": "string"},
                    "direction": {
                        "type": "string",
                        "enum": ["INBOUND", "OUTBOUND", "ANY"],
                        "default": "INBOUND",
                    },
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["stylized_fact_id"],
            },
        )
        self.server.register_tool(
            name="traverse_graph",
            handler=self._traverse_graph,
            description="Raw graph traversal from any ArangoDB vertex ID.",
            input_schema={
                "type": "object",
                "properties": {
                    "start_vertex": {
                        "type": "string",
                        "description": "ArangoDB vertex ID, e.g. 'documents/abc123'",
                    },
                    "graph_name": {
                        "type": "string",
                        "enum": [
                            "citation_graph",
                            "support_graph",
                            "taxonomy_graph",
                            "knowledge_graph",
                            "chunk_graph",
                        ],
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["OUTBOUND", "INBOUND", "ANY"],
                        "default": "ANY",
                    },
                    "max_depth": {"type": "integer", "default": 2},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["start_vertex", "graph_name"],
            },
        )
        self.server.register_tool(
            name="find_taxa_for_document",
            handler=self._find_taxa_for_document,
            description="Return organisms linked to a document via knowledge_graph edges.",
            input_schema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                },
                "required": ["document_id"],
            },
        )

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _unavailable(self) -> dict:
        return {"error": "ArangoDB unavailable", "items": []}

    async def _expand_context(
        self,
        chunk_ids: list[str],
        max_hops: int = 2,
        limit: int = 50,
    ) -> dict:
        if not self._graph_svc:
            return self._unavailable()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _executor,
            lambda: self._graph_svc.expand_from_chunks(chunk_ids, max_hops, limit),
        )
        return {
            "chunk_count": len(result["chunks"]),
            "document_count": len(result["documents"]),
            "fact_count": len(result["facts"]),
            "stylized_fact_count": len(result["stylized_facts"]),
            "taxon_count": len(result["taxa"]),
            "graph_path_steps": len(result["graph_path"]),
            **result,
        }

    async def _get_citation_chain(
        self, document_id: str, max_depth: int = 5
    ) -> dict:
        if not self._graph_svc:
            return self._unavailable()
        loop = asyncio.get_event_loop()
        chain = await loop.run_in_executor(
            _executor,
            lambda: self._graph_svc.get_citation_chain(document_id, max_depth),
        )
        return {"document_id": document_id, "depth": max_depth, "chain": chain}

    async def _find_related_facts(
        self,
        stylized_fact_id: str,
        direction: str = "INBOUND",
        limit: int = 20,
    ) -> dict:
        if not self._graph_svc:
            return self._unavailable()
        loop = asyncio.get_event_loop()
        facts = await loop.run_in_executor(
            _executor,
            lambda: self._graph_svc.find_related_facts(stylized_fact_id, direction, limit),
        )
        return {"stylized_fact_id": stylized_fact_id, "count": len(facts), "facts": facts}

    async def _traverse_graph(
        self,
        start_vertex: str,
        graph_name: str,
        direction: str = "ANY",
        max_depth: int = 2,
        limit: int = 50,
    ) -> dict:
        if not self._arango:
            return self._unavailable()
        loop = asyncio.get_event_loop()
        rows = await loop.run_in_executor(
            _executor,
            lambda: self._arango.traverse(
                start_vertex, graph_name, direction, 1, max_depth, limit
            ),
        )
        return {"start_vertex": start_vertex, "count": len(rows), "items": rows}

    async def _find_taxa_for_document(self, document_id: str) -> dict:
        if not self._graph_svc:
            return self._unavailable()
        loop = asyncio.get_event_loop()
        taxa = await loop.run_in_executor(
            _executor,
            lambda: self._graph_svc.find_taxa_for_document(document_id),
        )
        return {"document_id": document_id, "count": len(taxa), "taxa": taxa}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = GraphExplorerAgent()
    agent.run()
