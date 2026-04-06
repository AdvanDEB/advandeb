"""
RetrievalAgent — semantic and hybrid search agent (port 8081).

Tools exposed via MCP:
    semantic_search      — pure vector similarity search
    hybrid_search        — vector + keyword + RRF
    find_similar_chunks  — find chunks similar to a given chunk
    embed_query          — return the embedding vector for a query string

Run as standalone process:
    python -m advandeb_kb.agents.retrieval_agent
"""

from __future__ import annotations

import logging
from typing import Optional

from advandeb_kb.agents.base_agent import BaseAgent
from advandeb_kb.config.settings import settings
from advandeb_kb.services.cache_service import CacheService
from advandeb_kb.services.chromadb_service import ChromaDBService
from advandeb_kb.services.embedding_service import EmbeddingService
from advandeb_kb.services.hybrid_retrieval_service import HybridRetrievalService

logger = logging.getLogger(__name__)

AGENT_PORT = 8081


class RetrievalAgent(BaseAgent):
    """
    Agent specialized in semantic and hybrid document chunk retrieval.

    Combines:
      - EmbeddingService (sentence-transformers)
      - ChromaDBService (embedded vector store)
      - HybridRetrievalService (vector + keyword + RRF)
    """

    def __init__(self, port: int = AGENT_PORT, host: str = "localhost"):
        super().__init__(name="retrieval_agent", port=port, host=host)
        self._embedding_svc: Optional[EmbeddingService] = None
        self._chroma_svc: Optional[ChromaDBService] = None
        self._retrieval_svc: Optional[HybridRetrievalService] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Load embedding model and connect to ChromaDB."""
        import asyncio
        loop = asyncio.get_running_loop()

        # Load embedding model in thread pool (blocking)
        self._embedding_svc = EmbeddingService()
        await loop.run_in_executor(None, self._embedding_svc._load)

        self._chroma_svc = ChromaDBService()
        self._chroma_svc._ensure_connected()

        cache = CacheService(
            redis_url=settings.REDIS_URL if settings.REDIS_URL else None,
        )

        self._retrieval_svc = HybridRetrievalService(
            embedding_svc=self._embedding_svc,
            chromadb_svc=self._chroma_svc,
            cache=cache,
            # arango_db not required — keyword search falls back to no-op if absent
        )

        logger.info(
            "RetrievalAgent initialized — model=%s chromadb_count=%d",
            self._embedding_svc.model_name,
            self._chroma_svc.count(),
        )

    def register_tools(self) -> None:
        self.server.register_tool(
            name="semantic_search",
            handler=self._semantic_search,
            description=(
                "Search the knowledge base using semantic similarity. "
                "Returns the most relevant text chunks for a given query."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "top_k": {"type": "integer", "default": 10, "description": "Number of results"},
                    "domain_filter": {"type": "string", "description": "Filter by general_domain"},
                },
                "required": ["query"],
            },
        )
        self.server.register_tool(
            name="hybrid_search",
            handler=self._hybrid_search,
            description=(
                "Hybrid search combining vector similarity and keyword matching "
                "with Reciprocal Rank Fusion. Optionally applies LLM reranking."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "top_k": {"type": "integer", "default": 10},
                    "domain_filter": {"type": "string"},
                    "use_reranking": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
        )
        self.server.register_tool(
            name="find_similar_chunks",
            handler=self._find_similar_chunks,
            description="Find chunks similar to a given chunk ID.",
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string", "description": "Source chunk ID"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["chunk_id"],
            },
        )
        self.server.register_tool(
            name="embed_query",
            handler=self._embed_query,
            description="Return the embedding vector for a query string.",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                },
                "required": ["text"],
            },
        )

    # ------------------------------------------------------------------
    # Tool implementations (async)
    # ------------------------------------------------------------------

    async def _semantic_search(
        self,
        query: str,
        top_k: int = 10,
        domain_filter: Optional[str] = None,
    ) -> dict:
        results = await self._retrieval_svc.retrieve(
            query=query,
            top_k=top_k,
            domain_filter=domain_filter,
            use_reranking=False,
        )
        return {
            "query": query,
            "count": len(results),
            "chunks": [r.to_dict() for r in results],
        }

    async def _hybrid_search(
        self,
        query: str,
        top_k: int = 10,
        domain_filter: Optional[str] = None,
        use_reranking: bool = False,
    ) -> dict:
        results = await self._retrieval_svc.retrieve(
            query=query,
            top_k=top_k,
            domain_filter=domain_filter,
            use_reranking=use_reranking,
        )
        return {
            "query": query,
            "count": len(results),
            "chunks": [r.to_dict() for r in results],
            "reranked": use_reranking,
        }

    async def _find_similar_chunks(
        self, chunk_id: str, top_k: int = 5
    ) -> dict:
        # Fetch the source chunk embedding then search for neighbours
        source = self._chroma_svc.get_chunk(chunk_id)
        if not source:
            return {"error": f"Chunk not found: {chunk_id}", "chunks": []}

        import asyncio
        loop = asyncio.get_running_loop()
        query_vec = await loop.run_in_executor(
            None, self._embedding_svc.embed_text, source["text"]
        )
        hits = await loop.run_in_executor(
            None, lambda: self._chroma_svc.search(query_vec, n_results=top_k + 1)
        )
        # Exclude the source chunk itself
        similar = [h for h in hits if h["id"] != chunk_id][:top_k]
        return {"source_chunk_id": chunk_id, "count": len(similar), "chunks": similar}

    async def _embed_query(self, text: str) -> dict:
        import asyncio
        loop = asyncio.get_running_loop()
        vec = await loop.run_in_executor(None, self._embedding_svc.embed_text, text)
        return {"text": text, "dimension": len(vec), "embedding": vec}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    agent = RetrievalAgent()
    agent.run()
