"""
HybridRetrievalService — multi-source retrieval with Reciprocal Rank Fusion.

Retrieval pipeline:
  1. Vector search  — cosine similarity via ChromaDB embeddings
  2. Keyword search — BM25 over the ArangoSearch view on ``chunks``
                      (MongoDB $text fallback while the view does not exist)
  3. RRF fusion     — Reciprocal Rank Fusion to combine ranked lists
  4. LLM reranking  — optional reranking via Ollama for top candidates

Usage:
    svc = HybridRetrievalService(embedding_svc, chroma_svc, arango_db)
    results = await svc.retrieve("DEB energy allocation in fish", top_k=10)

Domains: every chunk belongs to one of DOMAINS. Chunks of the OpenAlex
abstract corpus carry ``general_domain == "reproduction"``; the full-text DEB
library carries "" or no ``general_domain`` at all (pipeline-written chunks
never set it), so anything that is not "reproduction" counts as "deb".
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx

from advandeb_kb.config.settings import settings
from advandeb_kb.services.embedding_service import EmbeddingService
from advandeb_kb.services.chromadb_service import ChromaDBService

logger = logging.getLogger(__name__)

# Thread pool for running sync operations inside async context
_executor = ThreadPoolExecutor(max_workers=4)

DOMAINS = ("deb", "reproduction")

# Domain filtering is done on an over-fetched, unfiltered vector query: a
# Chroma ``where`` on general_domain took 1.5-15 s on the 2.8M-vector store
# (an unfiltered query takes ~10 ms), and ``$ne`` fails outright there with
# "Error finding id". The fetch grows by this factor until enough hits of the
# requested domain are found or the cap is reached.
_DOMAIN_OVERFETCH = 5
_DOMAIN_FETCH_CAP = 2000

# How long a missing ArangoSearch view is remembered before checking again.
_VIEW_RECHECK_SECONDS = 600.0


def chunk_domain(metadata: Optional[dict]) -> str:
    """The domain a chunk belongs to (see module docstring)."""
    value = ((metadata or {}).get("general_domain") or "").strip().lower()
    return "reproduction" if value == "reproduction" else "deb"


def normalize_domain(domain_filter: Optional[str]) -> Optional[str]:
    """Validate a domain filter; None or "" means no filter."""
    if domain_filter is None or not str(domain_filter).strip():
        return None
    domain = str(domain_filter).strip().lower()
    if domain not in DOMAINS:
        raise ValueError(
            f"unknown domain_filter {domain_filter!r}; use one of {', '.join(DOMAINS)} "
            f"or omit it"
        )
    return domain


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

    @classmethod
    def from_dict(cls, data: dict) -> "RetrievalResult":
        return cls(
            chunk_id=data["chunk_id"],
            text=data.get("text", ""),
            metadata=dict(data.get("metadata") or {}),
            vector_rank=data.get("vector_rank"),
            keyword_rank=data.get("keyword_rank"),
            rrf_score=data.get("rrf_score", 0.0),
            llm_rank=data.get("llm_rank"),
        )


# ---------------------------------------------------------------------------
# HybridRetrievalService
# ---------------------------------------------------------------------------

class HybridRetrievalService:
    """
    Combines vector and keyword retrieval with Reciprocal Rank Fusion.

    Args:
        embedding_svc: EmbeddingService instance (sentence-transformers).
        chromadb_svc:  ChromaDBService instance (vector store).
        arango_db:     ArangoDatabase (or python-arango database) holding the
                       ``chunks`` collection and its ArangoSearch view.
        mongo_db:      Optional pymongo DB for the MongoDB $text fallback.
        ollama_url:    Ollama base URL for LLM reranking.
        rrf_k:         RRF constant (default 60, higher = smoother).
        keyword_backend: "auto" (BM25 view if it exists, else MongoDB),
                       "arango", "mongo" or "none". Defaults to
                       settings.RETRIEVAL_KEYWORD_BACKEND.
        rerank_model:  Ollama model for LLM reranking. Defaults to
                       settings.RERANK_MODEL.
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
        keyword_backend: Optional[str] = None,
        chunks_view: Optional[str] = None,
        text_analyzer: Optional[str] = None,
        rerank_model: Optional[str] = None,
    ):
        self.embedding_svc = embedding_svc
        self.chromadb_svc = chromadb_svc
        self.arango_db = arango_db
        self.mongo_db = mongo_db
        self.ollama_url = ollama_url or settings.OLLAMA_BASE_URL
        self.rrf_k = rrf_k
        self._cache = cache  # optional CacheService instance
        self.keyword_backend = (keyword_backend or settings.RETRIEVAL_KEYWORD_BACKEND).lower()
        self.chunks_view = chunks_view or settings.RETRIEVAL_CHUNKS_VIEW
        self.text_analyzer = text_analyzer or settings.RETRIEVAL_TEXT_ANALYZER
        self.rerank_model = rerank_model or settings.RERANK_MODEL

        self._view_ready: Optional[bool] = None
        self._view_checked_at = 0.0
        self._fallback_warned = False
        self._reranker_ok: Optional[bool] = None

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
            domain_filter:  "deb" or "reproduction" to restrict the corpus.
            use_reranking:  If True, call Ollama to rerank final candidates.
            rerank_top_k:   How many to pass to LLM reranker (subset of top_k).

        Returns:
            List of RetrievalResult ordered by relevance (best first).
        """
        domain = normalize_domain(domain_filter)

        # The fused ranking is deterministic and cached; reranking is applied
        # on top of it, so asking for reranking no longer skips the cache.
        results = self._cache_get(query, top_k, domain)
        if results is None:
            query_vec = await self._embed(query)
            vector_hits = await self._vector_hits(query_vec, top_k * 2, domain)
            keyword_hits = await self._keyword_search(query, limit=top_k * 2, domain=domain)

            fused = self._reciprocal_rank_fusion(vector_hits, keyword_hits)
            results = self._build_results(fused, vector_hits, keyword_hits, top_k)
            self._cache_set(query, top_k, domain, results)

            logger.debug(
                "retrieve: query=%r vector=%d keyword=%d fused=%d returned=%d",
                query[:60],
                len(vector_hits),
                len(keyword_hits),
                len(fused),
                len(results),
            )

        if use_reranking and results:
            results = await self._rerank_with_llm(query, results, top_n=rerank_top_k)
        return results

    async def vector_search(
        self,
        query: str,
        top_k: int = 10,
        domain_filter: Optional[str] = None,
    ) -> list[RetrievalResult]:
        """Pure vector similarity search (no keyword arm, no fusion)."""
        domain = normalize_domain(domain_filter)
        query_vec = await self._embed(query)
        # Over-fetch so dropping repeated passages still leaves top_k.
        hits = self._dedupe(await self._vector_hits(query_vec, top_k * 2, domain))
        return [
            RetrievalResult(
                chunk_id=h["id"],
                text=h["text"],
                metadata=h["metadata"],
                vector_rank=rank,
                rrf_score=1.0 / (self.rrf_k + rank + 1),
            )
            for rank, h in enumerate(hits[:top_k])
        ]

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
    # Cache (stores plain dicts so cached results are never shared objects
    # and survive the Redis backend's JSON round trip)
    # ------------------------------------------------------------------

    def _cache_get(self, query: str, top_k: int, domain: Optional[str]) -> Optional[list[RetrievalResult]]:
        if not self._cache:
            return None
        cached = self._cache.get(query, top_k=top_k, domain_filter=domain)
        if cached is None:
            return None
        try:
            return [RetrievalResult.from_dict(d) for d in cached]
        except (KeyError, TypeError, AttributeError):
            return None

    def _cache_set(self, query: str, top_k: int, domain: Optional[str], results: list[RetrievalResult]) -> None:
        if self._cache:
            self._cache.set(query, top_k=top_k, domain_filter=domain, value=[r.to_dict() for r in results])

    # ------------------------------------------------------------------
    # Vector search
    # ------------------------------------------------------------------

    async def _embed(self, query: str) -> list[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, self.embedding_svc.embed_query, query)

    async def _vector_hits(self, query_vec: list[float], n: int, domain: Optional[str]) -> list[dict]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _executor, lambda: self._vector_hits_sync(query_vec, n, domain)
        )

    def _vector_hits_sync(self, query_vec: list[float], n: int, domain: Optional[str]) -> list[dict]:
        if domain is None:
            return self.chromadb_svc.search(query_vec, n_results=n)
        fetch = n * _DOMAIN_OVERFETCH
        while True:
            hits = self.chromadb_svc.search(query_vec, n_results=fetch)
            kept = [h for h in hits if chunk_domain(h.get("metadata")) == domain]
            if len(kept) >= n or fetch >= _DOMAIN_FETCH_CAP or len(hits) < fetch:
                return kept[:n]
            fetch = min(fetch * _DOMAIN_OVERFETCH, _DOMAIN_FETCH_CAP)

    # ------------------------------------------------------------------
    # Keyword search  (BM25 over the ArangoSearch view, MongoDB fallback)
    # ------------------------------------------------------------------

    async def _keyword_search(
        self, query: str, limit: int = 40, domain: Optional[str] = None
    ) -> list[dict]:
        loop = asyncio.get_running_loop()
        backend = self._keyword_backend_for_query()
        if backend == "arango":
            return await loop.run_in_executor(
                _executor, lambda: self._arango_bm25_search(query, limit, domain)
            )
        if backend == "mongo":
            return await loop.run_in_executor(
                _executor, lambda: self._mongo_keyword_search(query, limit, domain)
            )
        return []

    def _keyword_backend_for_query(self) -> str:
        backend = self.keyword_backend
        if backend == "none":
            return "none"
        if backend == "mongo":
            return "mongo" if self.mongo_db is not None else "none"
        if self.arango_db is not None and self._bm25_view_ready():
            return "arango"
        if backend == "arango":
            return "none"
        # auto: the view is missing, so fall back to MongoDB $text. That
        # searches the frozen `chunks` collection of the old ingestion, not
        # the corpus the vector arm searches — say so once.
        if not self._fallback_warned:
            self._fallback_warned = True
            logger.warning(
                "Keyword search: ArangoSearch view %r not found; falling back to "
                "MongoDB $text over the legacy chunks collection. Create the view "
                "with knowledge-builder/scripts/setup_chunks_search_view.py.",
                self.chunks_view,
            )
        return "mongo" if self.mongo_db is not None else "none"

    def _raw_arango(self):
        # Accept either advandeb_kb's ArangoDatabase wrapper or a python-arango
        # StandardDatabase.
        return getattr(self.arango_db, "db", self.arango_db)

    def _bm25_view_ready(self) -> bool:
        now = time.monotonic()
        if self._view_ready or (
            self._view_ready is False and now - self._view_checked_at < _VIEW_RECHECK_SECONDS
        ):
            return bool(self._view_ready)
        self._view_checked_at = now
        try:
            self._view_ready = any(v["name"] == self.chunks_view for v in self._raw_arango().views())
        except Exception as exc:
            logger.warning("Keyword search: could not check view %r: %s", self.chunks_view, exc)
            self._view_ready = False
        return self._view_ready

    def _arango_bm25_search(
        self, query: str, limit: int, domain: Optional[str]
    ) -> list[dict]:
        """
        BM25-ranked search over the ArangoSearch view on ``chunks``.

        The query is tokenised with the view's analyzer (lower-casing, English
        stemming, stop words removed) and any token may match — BM25 ranks
        documents matching more and rarer terms higher, unlike the old
        FULLTEXT query, which required every word.
        """
        if domain == "reproduction":
            domain_clause = 'AND c.general_domain == "reproduction"'
        elif domain == "deb":
            domain_clause = 'AND NOT (c.general_domain == "reproduction")'
        else:
            domain_clause = ""
        aql = f"""
        LET terms = TOKENS(@query, @analyzer)
        FILTER LENGTH(terms) > 0
        FOR c IN @@view
            SEARCH ANALYZER(c.text IN terms, @analyzer) {domain_clause}
            SORT BM25(c) DESC
            LIMIT @limit
            RETURN {{
                id: c._key,
                text: c.text,
                score: BM25(c),
                metadata: {{
                    document_id: c.document_id,
                    chunk_index: c.chunk_index,
                    char_start: c.char_start,
                    char_end: c.char_end,
                    general_domain: c.general_domain,
                    source_path: c.source_path
                }}
            }}
        """
        bind = {
            "query": query,
            "analyzer": self.text_analyzer,
            "@view": self.chunks_view,
            "limit": limit,
        }
        try:
            cursor = self._raw_arango().aql.execute(aql, bind_vars=bind)
            hits = list(cursor)
        except Exception as exc:
            logger.warning("ArangoDB BM25 keyword search failed: %s", exc)
            # The view may have been dropped; re-check before the next query.
            self._view_ready = None
            return []
        for h in hits:
            h["metadata"] = {k: v for k, v in h["metadata"].items() if v is not None}
        return hits

    def _mongo_keyword_search(
        self, query: str, limit: int, domain: Optional[str]
    ) -> list[dict]:
        """MongoDB $text full-text search fallback (requires text index on chunks)."""
        try:
            filter_: dict = {"$text": {"$search": query}}
            if domain == "reproduction":
                filter_["general_domain"] = "reproduction"
            elif domain == "deb":
                filter_["general_domain"] = {"$ne": "reproduction"}
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

    @staticmethod
    def _passage_key(item: dict) -> str:
        """
        Identity of a passage for fusion: its whitespace-normalised text.

        The corpus holds most full-text papers more than once (two ingestion
        lineages in ChromaDB, a third in Arango ``chunks``), chunked
        identically, so the same passage comes back under different chunk
        ids. Keyed by id, a passage both arms found counted as two unrelated
        hits, and copies filled 2-4 of the top 10 slots.
        """
        text = item.get("text")
        if not text:
            return "id:" + str(item["id"])
        return hashlib.sha1(" ".join(text.split()).lower().encode()).hexdigest()

    @classmethod
    def _dedupe(cls, hits: list[dict]) -> list[dict]:
        """Drop repeated passages from one ranked list, keeping the best rank."""
        seen: set[str] = set()
        out = []
        for h in hits:
            key = cls._passage_key(h)
            if key not in seen:
                seen.add(key)
                out.append(h)
        return out

    def _reciprocal_rank_fusion(
        self,
        vector_results: list[dict],
        keyword_results: list[dict],
    ) -> dict[str, float]:
        """
        Compute RRF scores for all unique passages across both ranked lists.

        RRF(d) = Σ 1 / (k + rank(d))  for each list where d appears, with
        ranks counted after dropping repeated passages from each list.

        Returns dict mapping chunk_id → rrf_score, sorted descending; a passage
        is represented by the first chunk id it was seen under (vector first,
        whose metadata is the richer).
        """
        k = self.rrf_k
        scores: dict[str, float] = {}
        representative: dict[str, str] = {}

        for hits in (vector_results, keyword_results):
            for rank, item in enumerate(self._dedupe(hits)):
                cid = representative.setdefault(self._passage_key(item), item["id"])
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
        # Index deduplicated hits by passage for O(1) lookup
        vector_index = {self._passage_key(h): (rank, h) for rank, h in enumerate(self._dedupe(vector_hits))}
        keyword_index = {self._passage_key(h): (rank, h) for rank, h in enumerate(self._dedupe(keyword_hits))}
        passage_of: dict[str, str] = {}
        for h in vector_hits + keyword_hits:
            passage_of.setdefault(h["id"], self._passage_key(h))

        results = []
        for chunk_id, rrf_score in list(fused.items())[:top_k]:
            key = passage_of.get(chunk_id)
            vec = vector_index.get(key)
            kw = keyword_index.get(key)
            # Get hit data from whichever list contains it (prefer vector)
            hit = (vec or kw or (None, None))[1]
            if hit is None:
                continue

            results.append(
                RetrievalResult(
                    chunk_id=chunk_id,
                    text=hit["text"],
                    metadata=hit["metadata"],
                    vector_rank=vec[0] if vec else None,
                    keyword_rank=kw[0] if kw else None,
                    rrf_score=rrf_score,
                )
            )

        return results

    # ------------------------------------------------------------------
    # LLM reranking via Ollama
    # ------------------------------------------------------------------

    async def _reranker_available(self, client: httpx.AsyncClient) -> bool:
        """
        Check once whether the rerank model is installed. A missing model used
        to 404 on every chatbot search (it was hard-coded to "llama2", which is
        not installed) and was logged at every call.
        """
        if self._reranker_ok is not None:
            return self._reranker_ok
        try:
            resp = await client.get(f"{self.ollama_url}/api/tags")
            resp.raise_for_status()
            names = {m.get("name") for m in resp.json().get("models", [])}
        except Exception as exc:
            # Ollama unreachable: don't cache — it may come back.
            logger.warning("LLM reranker: cannot list Ollama models (%s); skipping rerank", exc)
            return False
        wanted = self.rerank_model if ":" in self.rerank_model else f"{self.rerank_model}:latest"
        self._reranker_ok = wanted in names or self.rerank_model in names
        if not self._reranker_ok:
            logger.warning(
                "LLM reranker disabled: model %r is not installed in Ollama at %s. "
                "Set RERANK_MODEL to an installed model, or CHAT_USE_RERANKING=false.",
                self.rerank_model,
                self.ollama_url,
            )
        return self._reranker_ok

    @staticmethod
    def _apply_rankings(
        candidates: list[RetrievalResult], rankings: list, top_n: int
    ) -> Optional[list[RetrievalResult]]:
        """
        Reorder ``candidates[:top_n]`` by the LLM's 1-based ``rankings``.

        Out-of-range, non-integer and repeated positions are ignored, and
        candidates the LLM left out keep their fused order after the ranked
        ones, so no candidate is ever dropped or duplicated. Returns None when
        the rankings contain nothing usable.
        """
        subset = candidates[:top_n]
        order: list[int] = []
        seen: set[int] = set()
        for pos in rankings:
            if isinstance(pos, str) and pos.strip().isdigit():
                pos = int(pos)
            if isinstance(pos, bool) or not isinstance(pos, int):
                continue
            if 1 <= pos <= len(subset) and pos not in seen:
                seen.add(pos)
                order.append(pos - 1)
        if not order:
            return None
        order.extend(i for i in range(len(subset)) if i + 1 not in seen)
        reranked = []
        for llm_rank, idx in enumerate(order):
            subset[idx].llm_rank = llm_rank
            reranked.append(subset[idx])
        return reranked + candidates[top_n:]

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
            async with httpx.AsyncClient(timeout=settings.RERANK_TIMEOUT) as client:
                if not await self._reranker_available(client):
                    return candidates
                resp = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.rerank_model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0},
                    },
                )
                if resp.status_code == 404:
                    # Model removed since the availability check.
                    self._reranker_ok = None
                resp.raise_for_status()
                data = resp.json()
                parsed = json.loads(data.get("response", "{}"))
                rankings = parsed.get("rankings", []) if isinstance(parsed, dict) else []

            reranked = self._apply_rankings(candidates, rankings, top_n)
            if reranked is None:
                logger.warning("LLM reranker returned no usable rankings, using RRF order")
                return candidates
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
