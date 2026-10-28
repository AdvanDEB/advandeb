"""HybridRetrievalService behaviour that needs no external services.

Covers the keyword-arm backend choice (BM25 view vs MongoDB fallback), the
domain filter (post-filtered, since Chroma ``where`` on general_domain is slow
and ``$ne`` fails on the production store), the LLM reranker (configurable
model, one warning when it is missing, no duplicated or dropped candidates)
and the cache, which reranking used to bypass.
"""

import logging

import pytest

from advandeb_kb.services import hybrid_retrieval_service as hrs
from advandeb_kb.services.hybrid_retrieval_service import (
    HybridRetrievalService,
    RetrievalResult,
    chunk_domain,
    normalize_domain,
)
from advandeb_kb.services.cache_service import CacheService


def _hit(i, domain=None, text=None):
    meta = {"document_id": f"d{i}", "chunk_index": 0}
    if domain is not None:
        meta["general_domain"] = domain
    return {"id": f"c{i}", "text": text or f"text {i}", "metadata": meta, "distance": i / 100}


class FakeEmbedding:
    dimension = 3

    def __init__(self):
        self.calls = 0

    def embed_query(self, query):
        self.calls += 1
        return [0.1, 0.2, 0.3]


class FakeChroma:
    def __init__(self, hits):
        self.hits = hits
        self.requests = []

    def search(self, query_embedding, n_results=10, where=None):
        assert where is None, "domain filtering must not use a Chroma where clause"
        self.requests.append(n_results)
        return self.hits[:n_results]


class FakeCursor(list):
    pass


class FakeAQL:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute(self, query, bind_vars=None):
        self.queries.append((query, bind_vars))
        return FakeCursor(self.rows)


class FakeArango:
    def __init__(self, views=("chunks_text_search",), rows=()):
        self._views = list(views)
        self.aql = FakeAQL(list(rows))

    def views(self):
        return [{"name": v} for v in self._views]


class FakeMongoChunks:
    def __init__(self):
        self.finds = 0

    def find(self, *a, **k):
        self.finds += 1
        return self

    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return iter([{"_id": "m1", "chunk_id": "m1", "text": "mongo hit", "document_id": "x"}])


class FakeMongo:
    def __init__(self):
        self.chunks = FakeMongoChunks()


def make_svc(hits=None, arango=None, mongo=None, backend="auto", cache=None, rerank_model="gemma3:latest"):
    return HybridRetrievalService(
        FakeEmbedding(),
        FakeChroma(hits if hits is not None else [_hit(i) for i in range(50)]),
        arango_db=arango,
        mongo_db=mongo,
        keyword_backend=backend,
        cache=cache,
        rerank_model=rerank_model,
        ollama_url="http://ollama.invalid",
    )


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------

def test_chunk_domain_treats_missing_and_empty_as_deb():
    assert chunk_domain({}) == "deb"
    assert chunk_domain({"general_domain": ""}) == "deb"
    assert chunk_domain({"general_domain": None}) == "deb"
    assert chunk_domain({"general_domain": "reproduction"}) == "reproduction"


def test_normalize_domain():
    assert normalize_domain(None) is None
    assert normalize_domain("  ") is None
    assert normalize_domain("DEB") == "deb"
    with pytest.raises(ValueError, match="unknown domain_filter"):
        normalize_domain("biology")


@pytest.mark.asyncio
async def test_domain_filter_post_filters_and_widens_the_fetch():
    # 3 deb chunks buried among reproduction ones: the first fetch (2n*5, as
    # vector_search over-fetches for dedup) is not enough, so it has to grow.
    hits = [_hit(i, "reproduction") for i in range(200)]
    for pos in (30, 120, 150):
        hits[pos] = _hit(pos, "")
    svc = make_svc(hits=hits, backend="none")
    results = await svc.vector_search("q", top_k=3, domain_filter="deb")
    assert [r.chunk_id for r in results] == ["c30", "c120", "c150"]
    assert svc.chromadb_svc.requests == [30, 150, 750]


@pytest.mark.asyncio
async def test_retrieve_rejects_unknown_domain():
    svc = make_svc(backend="none")
    with pytest.raises(ValueError):
        await svc.retrieve("q", domain_filter="ecology")


# ---------------------------------------------------------------------------
# Keyword arm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bm25_view_is_used_when_present():
    arango = FakeArango(rows=[{"id": "c7", "text": "text 7", "score": 3.2,
                               "metadata": {"document_id": "d7", "general_domain": None}}])
    mongo = FakeMongo()
    svc = make_svc(arango=arango, mongo=mongo)
    results = await svc.retrieve("starvation survival", top_k=5)
    assert mongo.chunks.finds == 0
    query, bind = arango.aql.queries[0]
    assert "BM25(c)" in query and "TOKENS(@query, @analyzer)" in query
    assert bind["@view"] == "chunks_text_search" and bind["analyzer"] == "advandeb_text_en"
    top = {r.chunk_id: r for r in results}
    assert top["c7"].keyword_rank == 0
    assert "general_domain" not in top["c7"].metadata  # nulls are dropped


@pytest.mark.asyncio
async def test_bm25_domain_clause():
    arango = FakeArango()
    svc = make_svc(arango=arango)
    svc._arango_bm25_search("q", 10, "deb")
    svc._arango_bm25_search("q", 10, "reproduction")
    deb_q, rep_q = arango.aql.queries[0][0], arango.aql.queries[1][0]
    assert 'NOT (c.general_domain == "reproduction")' in deb_q
    assert 'AND c.general_domain == "reproduction"' in rep_q


@pytest.mark.asyncio
async def test_missing_view_falls_back_to_mongo_with_one_warning(caplog):
    mongo = FakeMongo()
    svc = make_svc(arango=FakeArango(views=()), mongo=mongo)
    with caplog.at_level(logging.WARNING, logger=hrs.__name__):
        await svc.retrieve("first query", top_k=5)
        await svc.retrieve("second query", top_k=5)
    assert mongo.chunks.finds == 2
    assert sum("not found" in r.message for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_forced_arango_backend_without_view_returns_no_keyword_hits():
    mongo = FakeMongo()
    svc = make_svc(arango=FakeArango(views=()), mongo=mongo, backend="arango")
    assert await svc._keyword_search("q") == []
    assert mongo.chunks.finds == 0


def test_fusion_merges_the_same_passage_under_different_ids():
    svc = make_svc(backend="none")
    vector = [_hit(1, text="Growth  is fuelled\nby reserve."), _hit(2), _hit(3, text="growth is fuelled by reserve.")]
    keyword = [{"id": "k9", "text": "Growth is fuelled by reserve.", "metadata": {"document_id": "oid"}}, _hit(2)]
    fused = svc._reciprocal_rank_fusion(vector, keyword)
    assert list(fused) == ["c1", "c2"]  # c3 and k9 are copies of c1
    assert fused["c1"] == pytest.approx(2 / 61)
    results = svc._build_results(fused, vector, keyword, top_k=10)
    assert [(r.chunk_id, r.vector_rank, r.keyword_rank) for r in results] == [("c1", 0, 0), ("c2", 1, 1)]


@pytest.mark.asyncio
async def test_semantic_search_drops_repeated_passages():
    hits = [_hit(0, text="same"), _hit(1, text="same"), _hit(2), _hit(3)]
    svc = make_svc(hits=hits, backend="none")
    results = await svc.vector_search("q", top_k=3)
    assert [r.chunk_id for r in results] == ["c0", "c2", "c3"]


@pytest.mark.asyncio
async def test_semantic_search_is_vector_only():
    arango = FakeArango()
    svc = make_svc(arango=arango)
    results = await svc.vector_search("q", top_k=4)
    assert [r.chunk_id for r in results] == ["c0", "c1", "c2", "c3"]
    assert all(r.keyword_rank is None for r in results)
    assert arango.aql.queries == []


# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------

def _results(n):
    return [RetrievalResult(f"c{i}", f"text {i}", {"document_id": f"d{i}"}) for i in range(n)]


def test_apply_rankings_ignores_duplicates_and_keeps_every_candidate():
    cands = _results(6)
    out = HybridRetrievalService._apply_rankings(cands, [3, 3, 1, 9, "2", True, 0], top_n=4)
    ids = [r.chunk_id for r in out]
    assert ids == ["c2", "c0", "c1", "c3", "c4", "c5"]
    assert len(set(ids)) == len(ids) == 6
    assert [r.llm_rank for r in out[:4]] == [0, 1, 2, 3]


def test_apply_rankings_with_nothing_usable():
    assert HybridRetrievalService._apply_rankings(_results(3), [7, "x", None], top_n=3) is None


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeHTTP:
    """Stands in for httpx.AsyncClient; records calls on the class."""

    installed = ["gemma3:latest"]
    generate_payload = {"response": '{"rankings": [2, 1]}'}
    calls: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        FakeHTTP.calls.append(("GET", url))
        return FakeResponse(200, {"models": [{"name": n} for n in FakeHTTP.installed]})

    async def post(self, url, json=None):
        FakeHTTP.calls.append(("POST", url, json))
        return FakeResponse(200, FakeHTTP.generate_payload)


@pytest.fixture
def fake_http(monkeypatch):
    FakeHTTP.calls = []
    FakeHTTP.installed = ["gemma3:latest"]
    monkeypatch.setattr(hrs.httpx, "AsyncClient", FakeHTTP)
    return FakeHTTP


@pytest.mark.asyncio
async def test_missing_rerank_model_warns_once_and_skips(fake_http, caplog):
    fake_http.installed = ["deepseek-r1:latest"]
    svc = make_svc(backend="none", rerank_model="llama2")
    with caplog.at_level(logging.WARNING, logger=hrs.__name__):
        first = await svc._rerank_with_llm("q", _results(3))
        second = await svc._rerank_with_llm("q", _results(3))
    assert [r.chunk_id for r in first] == [r.chunk_id for r in second] == ["c0", "c1", "c2"]
    assert not any(c[0] == "POST" for c in fake_http.calls)
    assert sum(c[0] == "GET" for c in fake_http.calls) == 1
    assert sum("reranker disabled" in r.message for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_rerank_uses_configured_model(fake_http):
    svc = make_svc(backend="none", rerank_model="gemma3")  # ":latest" implied
    out = await svc._rerank_with_llm("q", _results(3), top_n=2)
    assert [r.chunk_id for r in out] == ["c1", "c0", "c2"]
    post = next(c for c in fake_http.calls if c[0] == "POST")
    assert post[2]["model"] == "gemma3"


@pytest.mark.asyncio
async def test_reranking_does_not_bypass_the_cache(fake_http):
    svc = make_svc(backend="none", cache=CacheService(redis_url=None))
    a = await svc.retrieve("same query", top_k=5, use_reranking=True)
    b = await svc.retrieve("same query", top_k=5, use_reranking=True)
    assert svc.embedding_svc.calls == 1
    assert [r.chunk_id for r in a] == [r.chunk_id for r in b]
    # Cached entries are not the objects handed out (rerank mutates llm_rank).
    assert a[0] is not b[0]
