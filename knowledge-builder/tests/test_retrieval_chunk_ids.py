"""
Every hybrid-retrieval hit carries a real chunk id.

On production ArangoDB (measured 2026-10-28) 2,201,278 of the 3.08M
``chunks`` — all reproduction abstracts, keyed ``W<openalex>_chunk_N`` by
scripts/embed_reproduction_abstracts.py — have no ``chunk_id`` field; on the
other 876,381 ``chunk_id == _key``. The keyword arm used to return
``id: doc.chunk_id``, so every reproduction hit came back with ``id: None``.
RRF keys scores by id, so all of them merged into one ``None`` entry scored
with their summed ranks, and a result with chunk_id None reached the caller.

These tests pin both halves of the fix: the keyword arm projects ``_key``,
and fusion never emits a None or empty chunk id whatever an arm returns.

No ArangoDB required: queries are recorded and answered from in-memory
chunk documents, not executed.

Run:
    conda run -n advandeb pytest tests/test_retrieval_chunk_ids.py -v
"""

import logging
import re

import pytest

from advandeb_kb.database.arango_client import ArangoDatabase
from advandeb_kb.services import hybrid_retrieval_service as hrs
from advandeb_kb.services.hybrid_retrieval_service import HybridRetrievalService

# Chunk documents shaped like the two production lineages.
REPRODUCTION_CHUNK = {  # embed_reproduction_abstracts.py: no chunk_id field
    "_key": "W2741809807_chunk_0",
    "document_id": "W2741809807",
    "chunk_index": 0,
    "general_domain": "reproduction",
    "text": "Clutch size increases with female body length in Daphnia.",
}
REPRODUCTION_CHUNK_2 = {
    "_key": "W1995017064_chunk_1",
    "document_id": "W1995017064",
    "chunk_index": 1,
    "general_domain": "reproduction",
    "text": "Egg production stops below a threshold food density.",
}
DEB_CHUNK = {  # pipeline-written: chunk_id == _key
    "_key": "doc_5f1c_chunk_3",
    "chunk_id": "doc_5f1c_chunk_3",
    "document_id": "doc_5f1c",
    "chunk_index": 3,
    "text": "The kappa rule allocates a fixed fraction of mobilised reserve to soma.",
}

_ID_PROJECTION = re.compile(r"\bid:\s*c\.(\w+)")


class FakeAQL:
    """Records each query and answers it from ``docs``, evaluating only the
    RETURN projection of ``id`` — the part these tests are about."""

    def __init__(self, docs):
        self.docs = docs
        self.queries: list[tuple[str, dict]] = []

    def execute(self, query, bind_vars=None):
        self.queries.append((query, bind_vars or {}))
        match = _ID_PROJECTION.search(query)
        assert match, f"no `id: c.<attr>` projection in:\n{query}"
        attr = match.group(1)
        return iter([
            {
                "id": doc.get(attr),
                "text": doc["text"],
                "score": 1.0,
                "metadata": {
                    "document_id": doc.get("document_id"),
                    "chunk_index": doc.get("chunk_index"),
                    "general_domain": doc.get("general_domain"),
                },
            }
            for doc in self.docs
        ])


class FakeStandardDatabase:
    """The python-arango StandardDatabase surface the service touches."""

    def __init__(self, docs, views=("chunks_text_search",)):
        self.aql = FakeAQL(docs)
        self._views = views

    def views(self):
        return [{"name": v} for v in self._views]


class RecordingArango(ArangoDatabase):
    """ArangoDatabase whose connection is a recorder (never connect())."""

    def __init__(self, docs) -> None:
        super().__init__(url="http://unused", db_name="unused",
                         username="unused", password="unused")
        self._db = FakeStandardDatabase(docs)

    @property
    def queries(self):
        return self._db.aql.queries


class FakeEmbedding:
    dimension = 3

    def embed_query(self, query):
        return [0.1, 0.2, 0.3]


class FakeChroma:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query_embedding, n_results=10, where=None):
        return self.hits[:n_results]


def _vector_hit(doc):
    # ChromaDB ids are the Arango _key for every lineage.
    return {
        "id": doc["_key"],
        "text": doc["text"],
        "metadata": {k: doc[k] for k in ("document_id", "chunk_index", "general_domain") if k in doc},
        "distance": 0.1,
    }


def _hit(cid, text):
    return {"id": cid, "text": text, "metadata": {"document_id": "d"}}


def make_svc(vector_hits=(), arango=None, mongo=None, backend="arango"):
    return HybridRetrievalService(
        FakeEmbedding(),
        FakeChroma(list(vector_hits)),
        arango_db=arango,
        mongo_db=mongo,
        keyword_backend=backend,
        ollama_url="http://ollama.invalid",
    )


# ---------------------------------------------------------------------------
# Keyword arm: ids come from _key
# ---------------------------------------------------------------------------

def test_bm25_hit_id_is_the_key_even_without_chunk_id_field():
    arango = RecordingArango([REPRODUCTION_CHUNK, DEB_CHUNK])
    hits = make_svc(arango=arango)._arango_bm25_search("clutch size", 10, None)

    assert [h["id"] for h in hits] == ["W2741809807_chunk_0", "doc_5f1c_chunk_3"]
    (query, _bind), = arango.queries
    assert "chunk_id" not in query


async def test_reproduction_chunk_found_by_both_arms_fuses_into_one_result():
    arango = RecordingArango([REPRODUCTION_CHUNK, REPRODUCTION_CHUNK_2, DEB_CHUNK])
    svc = make_svc(vector_hits=[_vector_hit(DEB_CHUNK), _vector_hit(REPRODUCTION_CHUNK)], arango=arango)

    results = await svc.retrieve("clutch size", top_k=10)

    by_id = {r.chunk_id: r for r in results}
    assert set(by_id) == {"W2741809807_chunk_0", "W1995017064_chunk_1", "doc_5f1c_chunk_3"}
    assert (by_id["W2741809807_chunk_0"].vector_rank, by_id["W2741809807_chunk_0"].keyword_rank) == (1, 0)
    # Found by the keyword arm only, and still a result of its own.
    assert (by_id["W1995017064_chunk_1"].vector_rank, by_id["W1995017064_chunk_1"].keyword_rank) == (None, 1)


def test_mongo_fallback_null_chunk_id_falls_back_to_object_id():
    class Cursor:
        def sort(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return iter([{"_id": "65f0a1", "chunk_id": None, "text": "legacy hit", "document_id": "x"}])

    class Mongo:
        class chunks:
            @staticmethod
            def find(*a, **k):
                return Cursor()

    hits = make_svc(mongo=Mongo(), backend="mongo")._mongo_keyword_search("legacy", 5, None)
    assert [h["id"] for h in hits] == ["65f0a1"]


# ---------------------------------------------------------------------------
# Fusion never produces a None chunk id
# ---------------------------------------------------------------------------

_NO_ID = [
    pytest.param(lambda h: h.update(id=None), id="None"),
    pytest.param(lambda h: h.update(id=""), id="empty"),
    pytest.param(lambda h: h.pop("id"), id="missing"),
]


@pytest.mark.parametrize("strip_id", _NO_ID)
def test_rrf_drops_hits_without_an_id(strip_id, caplog):
    svc = make_svc(backend="none")
    vector = [_hit("c1", "alpha"), _hit("c2", "beta")]
    keyword = [_hit("x", f"orphan {i}") for i in range(3)] + [_hit("c2", "beta"), _hit("k5", "gamma")]
    for h in keyword[:3]:
        strip_id(h)

    with caplog.at_level(logging.WARNING, logger=hrs.__name__):
        fused = svc._reciprocal_rank_fusion(vector, keyword)
    results = svc._build_results(fused, vector, keyword, top_k=10)

    assert all(fused), f"falsy chunk id in fused scores: {list(fused)}"
    assert list(fused) == ["c2", "c1", "k5"]
    # Keyword ranks are counted after the id-less hits are dropped.
    assert fused["c2"] == pytest.approx(1 / 62 + 1 / 61)
    assert [(r.chunk_id, r.vector_rank, r.keyword_rank) for r in results] == [
        ("c2", 1, 0), ("c1", 0, None), ("k5", None, 1),
    ]
    assert sum("without a chunk id" in r.message for r in caplog.records) == 1


def test_rrf_with_only_id_less_hits_is_empty():
    svc = make_svc(backend="none")
    keyword = [{"id": None, "text": f"t{i}", "metadata": {}} for i in range(4)]
    keyword.append({"id": None, "text": "", "metadata": {}})  # no text either
    fused = svc._reciprocal_rank_fusion([], keyword)
    assert fused == {}
    assert svc._build_results(fused, [], keyword, top_k=10) == []


async def test_semantic_search_never_returns_a_none_chunk_id():
    hits = [_hit("c0", "a"), {"id": None, "text": "b", "metadata": {}}, _hit("c2", "c")]
    results = await make_svc(vector_hits=hits, backend="none").vector_search("q", top_k=5)
    assert [r.chunk_id for r in results] == ["c0", "c2"]
