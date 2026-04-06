"""
HybridRetrievalService — multi-source retrieval with Reciprocal Rank Fusion.

Retrieval pipeline:
  1. Vector search  — cosine similarity via ChromaDB embeddings
  2. Keyword search — full-text search via ArangoDB (or MongoDB fallback)
  3. RRF fusion     — Reciprocal Rank Fusion to combine ranked lists
  4. LLM reranking  — optional reranking via Ollama for top candidates

Usage:
    svc = HybridRetrievalService(embedding_svc, chroma_svc, arango_db)
    results = await svc.retrieve("DEB energy allocation in fish", top_k=10)
"""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import httpx

from advandeb_kb.config.settings import settings
from advandeb_kb.services.embedding_service import EmbeddingService
from advandeb_kb.services.chromadb_service import ChromaDBService

logger = logging.getLogger(__name__)

# Thread pool for running sync operations inside async context
_executor = ThreadPoolExecutor(max_workers=4)


# ---------------------------------------------------------------------------
# Result dataclass (plain dict-compatible)
# ---------------------------------------------------------------------------

class RetrievalResult:
    """A single retrieved chunk with fusion metadata."""

    __slots__ = ("chunk_id", "text", "metadata", "vector_rank", "keyword_rank", "rrf_score", "llm_rank")

    def __init__(
        self,
        chunk_id: str,
        text: str,
        metadata: dict,
        vector_rank: Optional[int] = None,
        keyword_rank: Optional[int] = None,
        rrf_score: float = 0.0,
        llm_rank: Optional[int] = None,
    ):
        self.chunk_id = chunk_id
        self.text = text
        self.metadata = metadata
        self.vector_rank = vector_rank
        self.keyword_rank = keyword_rank
        self.rrf_score = rrf_score
        self.llm_rank = llm_rank

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "metadata": self.metadata,
            "vector_rank": self.vector_rank,
            "keyword_rank": self.keyword_rank,
            "rrf_score": self.rrf_score,
            "llm_rank": self.llm_rank,
            "document_id": self.metadata.get("document_id", ""),
        }


# ---------------------------------------------------------------------------
# HybridRetrievalService
# ---------------------------------------------------------------------------

class HybridRetrievalService:
    """
    Combines vector and keyword retrieval with Reciprocal Rank Fusion.

    Args:
        embedding_svc: EmbeddingService instance (sentence-transformers).
        chromadb_svc:  ChromaDBService instance (vector store).
        arango_db:     ArangoDatabase instance — if None, keyword search falls
                       back to MongoDB full-text (requires text index).
        mongo_db:      Optional pymongo DB for MongoDB keyword fallback.
        ollama_url:    Ollama base URL for LLM reranking.
        rrf_k:         RRF constant (default 60, higher = smoother).
    """

    def __init__(
        self,
        embedding_svc: EmbeddingService,
        chromadb_svc: ChromaDBService,
        arango_db=None,
        mongo_db=None,
        ollama_url: Optional[str] = None,
        rrf_k: int = 60,
        cache=None,
    ):
        self.embedding_svc = embedding_svc
        self.chromadb_svc = chromadb_svc
        self.arango_db = arango_db
        self.mongo_db = mongo_db
        self.ollama_url = ollama_url or settings.OLLAMA_BASE_URL
        self.rrf_k = rrf_k
        self._cache = cache  # optional CacheService instance

    # ------------------------------------------------------------------
    # Public retrieval API
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        top_k: int = 20,
        domain_filter: Optional[str] = None,
        use_reranking: bool = False,
        rerank_top_k: int = 10,
    ) -> list[RetrievalResult]:
        """
        Hybrid retrieval: vector + keyword → RRF → optional LLM rerank.

        Args:
            query:          Natural language search query.
            top_k:          Number of results to return after fusion.
            domain_filter:  If set, restrict to chunks with matching general_domain.
            use_reranking:  If True, call Ollama to rerank final candidates.
            rerank_top_k:   How many to pass to LLM reranker (subset of top_k).

        Returns:
            List of RetrievalResult ordered by relevance (best first).
        """
        # Cache check (skip when reranking — results vary)
        if self._cache and not use_reranking:
            cached = self._cache.get(query, top_k=top_k, domain_filter=domain_filter)
            if cached is not None:
                return cached

        loop = asyncio.get_running_loop()

        # 1. Embed query (blocking → run in thread pool)
        query_vec = await loop.run_in_executor(
            _executor, self.embedding_svc.embed_query, query
        )

        # 2. Vector search (blocking ChromaDB call)
        chroma_where = {"general_domain": domain_filter} if domain_filter else None
        vector_hits = await loop.run_in_executor(
            _executor,
            lambda: self.chromadb_svc.search(
                query_vec, n_results=top_k * 2, where=chroma_where
            ),
        )

        # 3. Keyword search (async-compatible)
        keyword_hits = await self._keyword_search(query, limit=top_k * 2, domain=domain_filter)

        # 4. Reciprocal Rank Fusion
        fused = self._reciprocal_rank_fusion(vector_hits, keyword_hits)

        # 5. Build results ordered by RRF score
        results = self._build_results(fused, vector_hits, keyword_hits, top_k)

        # 6. Optional LLM reranking on top candidates
        if use_reranking and results:
            results = await self._rerank_with_llm(query, results, top_n=rerank_top_k)

        logger.debug(
            "retrieve: query=%r vector=%d keyword=%d fused=%d returned=%d",
            query[:60],
            len(vector_hits),
            len(keyword_hits),
            len(fused),
            len(results),
        )

        # Store in cache (only non-reranked results — deterministic)
        if self._cache and not use_reranking:
            self._cache.set(query, top_k=top_k, domain_filter=domain_filter, value=results)

        return results

    async def retrieve_for_document(self, document_id: str, top_k: int = 20) -> list[RetrievalResult]:
        """Fetch all stored chunks for a specific document (no query needed)."""
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(
            _executor,
            lambda: self.chromadb_svc.search(
                [0.0] * self.embedding_svc.dimension,  # dummy vector
                n_results=top_k,
                where={"document_id": document_id},
            ),
        )
        return [
            RetrievalResult(
                chunk_id=h["id"],
                text=h["text"],
                metadata=h["metadata"],
            )
            for h in raw
        ]

    # ------------------------------------------------------------------
    # Keyword search  (ArangoDB full-text or MongoDB fallback)
    # ------------------------------------------------------------------

    async def _keyword_search(
        self, query: str, limit: int = 40, domain: Optional[str] = None
    ) -> list[dict]:
        loop = asyncio.get_running_loop()

        if self.arango_db is not None:
            return await loop.run_in_executor(
                _executor, lambda: self._arango_keyword_search(query, limit, domain)
            )
        elif self.mongo_db is not None:
            return await loop.run_in_executor(
                _executor, lambda: self._mongo_keyword_search(query, limit, domain)
            )
        return []

    def _arango_keyword_search(
        self, query: str, limit: int, domain: Optional[str]
    ) -> list[dict]:
        """Full-text search via ArangoDB FULLTEXT index."""
        try:
            # Build FULLTEXT-compatible query (prefix search with comma separation)
            ft_query = ",".join(f"prefix:{w}" for w in query.split() if len(w) > 2)
            aql = """
            FOR doc IN FULLTEXT('chunks', 'text', @query)
                FILTER @domain == null OR doc.general_domain == @domain
                LIMIT @limit
                RETURN {
                    id: doc.chunk_id,
                    text: doc.text,
                    metadata: {
                        document_id: doc.document_id,
                        chunk_index: doc.chunk_index,
                        char_start: doc.char_start,
                        char_end: doc.char_end,
                        general_domain: doc.general_domain
                    }
                }
            """
            return self.arango_db.aql(
                aql, bind_vars={"query": ft_query, "domain": domain, "limit": limit}
            )
        except Exception as exc:
            logger.warning("ArangoDB keyword search failed: %s", exc)
            return []

    def _mongo_keyword_search(
        self, query: str, limit: int, domain: Optional[str]
    ) -> list[dict]:
        """MongoDB $text full-text search fallback (requires text index on chunks)."""
        try:
            filter_: dict = {"$text": {"$search": query}}
            if domain:
                filter_["general_domain"] = domain
            cursor = self.mongo_db.chunks.find(
                filter_,
                {"score": {"$meta": "textScore"}, "chunk_id": 1, "text": 1,
                 "document_id": 1, "chunk_index": 1, "char_start": 1, "char_end": 1},
            ).sort([("score", {"$meta": "textScore"})]).limit(limit)

            results = []
            for doc in cursor:
                results.append({
                    "id": doc.get("chunk_id", str(doc["_id"])),
                    "text": doc.get("text", ""),
                    "metadata": {
                        "document_id": str(doc.get("document_id", "")),
                        "chunk_index": doc.get("chunk_index", 0),
                        "char_start": doc.get("char_start", 0),
                        "char_end": doc.get("char_end", 0),
                    },
                })
            return results
        except Exception as exc:
            logger.warning("MongoDB keyword search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Reciprocal Rank Fusion
    # ------------------------------------------------------------------

    def _reciprocal_rank_fusion(
        self,
        vector_results: list[dict],
        keyword_results: list[dict],
    ) -> dict[str, float]:
        """
        Compute RRF scores for all unique chunk IDs across both ranked lists.

        RRF(d) = Σ 1 / (k + rank(d))  for each list where d appears.

        Returns dict mapping chunk_id → rrf_score, sorted descending.
        """
        k = self.rrf_k
        scores: dict[str, float] = {}

        for rank, item in enumerate(vector_results):
            cid = item["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)

        for rank, item in enumerate(keyword_results):
            cid = item["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)

        return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))

    def _build_results(
        self,
        fused: dict[str, float],
        vector_hits: list[dict],
        keyword_hits: list[dict],
        top_k: int,
    ) -> list[RetrievalResult]:
        """Build RetrievalResult list from fusion scores + raw hit metadata."""
        # Index raw hits by chunk_id for O(1) lookup
        vector_index = {h["id"]: (rank, h) for rank, h in enumerate(vector_hits)}
        keyword_index = {h["id"]: (rank, h) for rank, h in enumerate(keyword_hits)}

        results = []
        for chunk_id, rrf_score in list(fused.items())[:top_k]:
            # Get hit data from whichever list contains it (prefer vector)
            if chunk_id in vector_index:
                vrank, hit = vector_index[chunk_id]
            elif chunk_id in keyword_index:
                vrank = None
                _, hit = keyword_index[chunk_id]
            else:
                continue

            krank = keyword_index[chunk_id][0] if chunk_id in keyword_index else None

            results.append(
                RetrievalResult(
                    chunk_id=chunk_id,
                    text=hit["text"],
                    metadata=hit["metadata"],
                    vector_rank=vector_index[chunk_id][0] if chunk_id in vector_index else None,
                    keyword_rank=krank,
                    rrf_score=rrf_score,
                )
            )

        return results

    # ------------------------------------------------------------------
    # LLM reranking via Ollama
    # ------------------------------------------------------------------

    async def _rerank_with_llm(
        self,
        query: str,
        candidates: list[RetrievalResult],
        top_n: int = 10,
    ) -> list[RetrievalResult]:
        """
        Ask Ollama to rerank the top candidates by relevance to query.
        Falls back to RRF order on any error.
        """
        if len(candidates) <= 1:
            return candidates

        subset = candidates[:top_n]
        numbered = "\n".join(
            f"[{i+1}] {r.text[:300]}..." if len(r.text) > 300 else f"[{i+1}] {r.text}"
            for i, r in enumerate(subset)
        )

        prompt = (
            f'Given the query: "{query}"\n\n'
            f"Rank these passages from most to least relevant.\n"
            f"Return ONLY a JSON object like: {{\"rankings\": [3, 1, 2, ...]}}\n\n"
            f"Passages:\n{numbered}"
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": "llama2",
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                raw_response = data.get("response", "{}")
                parsed = json.loads(raw_response)
                rankings: list[int] = parsed.get("rankings", [])

            if not rankings or len(rankings) != len(subset):
                logger.warning("LLM reranker returned invalid rankings, using RRF order")
                return candidates

            # Apply rankings (1-indexed)
            reranked = []
            for llm_rank, position in enumerate(rankings):
                if 1 <= position <= len(subset):
                    result = subset[position - 1]
                    result.llm_rank = llm_rank
                    reranked.append(result)

            # Append any remaining candidates not in reranked subset
            reranked_ids = {r.chunk_id for r in reranked}
            reranked.extend(r for r in candidates[top_n:] if r.chunk_id not in reranked_ids)

            return reranked

        except Exception as exc:
            logger.warning("LLM reranking failed (%s), using RRF order", exc)
            return candidates

    # ------------------------------------------------------------------
    # Convenience: dict output for API responses
    # ------------------------------------------------------------------

    async def retrieve_as_dicts(self, query: str, **kwargs) -> list[dict]:
        results = await self.retrieve(query, **kwargs)
        return [r.to_dict() for r in results]
