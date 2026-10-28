"""
Pins how GraphExpansionService.expand_from_chunks looks up chunks and their
parent documents: by _key, through the primary index.

It used to filter chunks on `chunk_id` and documents on `mongo_id`. Neither
attribute is indexed, so each chat turn scanned 3.08M chunks (~1 s) and
3.9M documents (~2.5 s). On production (2026-10-28):

  - every chunk that has a chunk_id has chunk_id == _key; the 2.2M
    reproduction abstracts (W<openalex>_chunk_N) have no chunk_id at all,
    though ChromaDB returns their _key as the retrieval id. They now
    resolve; before, they were silently dropped.
  - no document has a mongo_id, so `documents` was always empty. Parent
    documents (chunk.document_id) are document _keys. They now appear,
    reduced to metadata: full-text papers carry ~100 KB of `content`.

No ArangoDB required: lookups are answered from memory, as the primary
index would answer them, and every query is recorded.

Run:
    conda run -n advandeb pytest tests/test_expansion_lookups.py -v
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.database.arango_client import ArangoDatabase
from advandeb_kb.services.graph_expansion_service import GraphExpansionService

_KEY_LOOKUP_RE = re.compile(r"FOR\s+doc\s+IN\s+@@col\s+FILTER\s+doc\._key\s+IN\s+@keys\b")


class KeyLookupArango(ArangoDatabase):
    """ArangoDatabase that answers _key lookups from in-memory collections
    and gives every other query (traversals, facts) no rows. Records every
    query with its bind vars."""

    def __init__(self, collections: dict[str, dict[str, dict]]) -> None:
        super().__init__(url="http://unused", db_name="unused",
                         username="unused", password="unused")
        self.collections = collections
        self.queries: list[tuple[str, dict]] = []

    def aql(self, query, bind_vars=None):
        bind_vars = bind_vars or {}
        self.queries.append((query, bind_vars))
        if not _KEY_LOOKUP_RE.search(query):
            return []
        col = self.collections.get(bind_vars["@col"], {})
        docs = [col[k] for k in bind_vars["keys"] if k in col]
        if "KEEP(doc, @fields)" in query:
            docs = [{f: d[f] for f in bind_vars["fields"] if f in d} for d in docs]
        return docs

    def lookups(self, collection: str) -> list[dict]:
        return [b for q, b in self.queries
                if _KEY_LOOKUP_RE.search(q) and b.get("@col") == collection]

    def traversal_starts(self, graph: str) -> set[str]:
        return {s for _, b in self.queries if b.get("graph") == graph
                for s in b["starts"]}


OBJECTID_DOC = "69d43eee915338a7a9da7585"
HASH_DOC = "doc_37ff5532b95657b9"
REPRO_DOC = "W2953039196"

OBJECTID_CHUNK = f"{OBJECTID_DOC}_chunk_3"
HASH_CHUNK = f"{HASH_DOC}_chunk_1325"
REPRO_CHUNK = f"{REPRO_DOC}_chunk_0"


def _chunk(key: str, doc: str, chunk_id: bool) -> dict:
    c = {"_id": f"chunks/{key}", "_key": key, "document_id": doc, "text": "t"}
    if chunk_id:  # backfilled from ChromaDB: a copy of _key
        c["chunk_id"] = key
    return c


def _document(key: str) -> dict:
    # As on production: no mongo_id.
    return {
        "_id": f"documents/{key}", "_key": key, "_rev": "r",
        "title": f"Title {key}", "authors": ["A. Author"], "year": 2020,
        "doi": f"10.1/{key}", "content": "x" * 100_000, "abstract": "y" * 3_000,
        "references": ["r"] * 50, "referenced_works": ["W1"] * 50,
    }


def _db() -> KeyLookupArango:
    return KeyLookupArango({
        "chunks": {
            OBJECTID_CHUNK: _chunk(OBJECTID_CHUNK, OBJECTID_DOC, chunk_id=True),
            HASH_CHUNK: _chunk(HASH_CHUNK, HASH_DOC, chunk_id=True),
            REPRO_CHUNK: _chunk(REPRO_CHUNK, REPRO_DOC, chunk_id=False),
        },
        "documents": {k: _document(k) for k in (OBJECTID_DOC, HASH_DOC, REPRO_DOC)},
    })


ALL_CHUNKS = [OBJECTID_CHUNK, HASH_CHUNK, REPRO_CHUNK]


# ------------------------------------------------------------------
# Chunks
# ------------------------------------------------------------------

def test_chunks_resolve_by_key_in_every_lineage():
    db = _db()
    out = GraphExpansionService(db).expand_from_chunks(ALL_CHUNKS + ["not_a_chunk"])
    assert {c["_key"] for c in out["chunks"]} == set(ALL_CHUNKS)
    assert db.traversal_starts("chunk_graph") == {f"chunks/{k}" for k in ALL_CHUNKS}


def test_chunk_without_chunk_id_resolves():
    # The reproduction abstracts: ChromaDB id == Arango _key, no chunk_id.
    db = _db()
    out = GraphExpansionService(db).expand_from_chunks([REPRO_CHUNK])
    assert [c["_key"] for c in out["chunks"]] == [REPRO_CHUNK]
    assert [d["_key"] for d in out["documents"]] == [REPRO_DOC]
    assert db.traversal_starts("knowledge_graph") == {f"documents/{REPRO_DOC}"}


def test_chunks_are_fetched_in_one_query():
    db = _db()
    GraphExpansionService(db).expand_from_chunks(ALL_CHUNKS)
    lookups = db.lookups("chunks")
    assert len(lookups) == 1
    assert lookups[0]["keys"] == ALL_CHUNKS


def test_unknown_chunks_stop_after_one_query():
    db = _db()
    out = GraphExpansionService(db).expand_from_chunks(["nope_chunk_0", "nope_chunk_1"])
    assert out == {"chunks": [], "documents": [], "facts": [],
                   "stylized_facts": [], "taxa": [], "graph_path": []}
    assert len(db.queries) == 1


def test_no_chunk_ids_sends_nothing():
    db = _db()
    GraphExpansionService(db).expand_from_chunks([])
    assert db.queries == []


# ------------------------------------------------------------------
# Parent documents
# ------------------------------------------------------------------

def test_parent_documents_resolve_by_key():
    # No document has a mongo_id; the old lookup always returned [].
    db = _db()
    out = GraphExpansionService(db).expand_from_chunks(ALL_CHUNKS)
    assert {d["_key"] for d in out["documents"]} == {OBJECTID_DOC, HASH_DOC, REPRO_DOC}
    lookups = db.lookups("documents")
    assert len(lookups) == 1
    assert set(lookups[0]["keys"]) == {OBJECTID_DOC, HASH_DOC, REPRO_DOC}


def test_parent_documents_are_metadata_only():
    out = GraphExpansionService(_db()).expand_from_chunks(ALL_CHUNKS)
    assert len(out["documents"]) == 3
    for d in out["documents"]:
        assert d["_id"] == f"documents/{d['_key']}"
        assert d["title"] == f"Title {d['_key']}"
        assert d["year"] == 2020
        assert not {"content", "abstract", "references", "referenced_works", "_rev"} & d.keys()


def test_provenance_trace_cites_parent_documents():
    svc = GraphExpansionService(_db())
    expansion = svc.expand_from_chunks(ALL_CHUNKS)
    trace = svc.build_provenance_trace("q", ALL_CHUNKS, expansion)
    assert set(trace.documents_cited) == {OBJECTID_DOC, HASH_DOC, REPRO_DOC}


# ------------------------------------------------------------------
# No scans
# ------------------------------------------------------------------

def test_no_lookup_filters_on_unindexed_copies_of_key():
    # chunks.chunk_id and documents.mongo_id have no index: filtering on
    # either is a full-collection scan.
    db = _db()
    GraphExpansionService(db).expand_from_chunks(ALL_CHUNKS)
    assert db.queries
    for query, bind_vars in db.queries:
        assert not re.search(r"\b(chunk_id|mongo_id)\b", query), query
        assert "chunk_id" not in bind_vars.values()
        assert "mongo_id" not in bind_vars.values()
