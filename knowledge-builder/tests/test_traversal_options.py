"""
Pins the OPTIONS clause of every AQL graph traversal, and the batching of
GraphExpansionService._traverse_graph.

ArangoDB (3.12 here) rejects `uniqueVertices: 'global'` unless the traversal
order is 'bfs' or 'weighted': [HTTP 400][ERR 10]. The code used to send
`bfsMode: true`, which is not an ArangoDB option, so every traversal failed,
the failure was logged as a warning, and chat graph expansion silently
returned nothing.

_traverse_graph used to send one query per start vertex; expand_from_chunks
feeds it every fact of every parent document (thousands), so one chat turn
cost thousands of round-trips. It now sends one query for all starts, with
each start still its own traversal so LIMIT and global uniqueness stay
per start.

No ArangoDB required: queries are captured, not executed.

Run:
    conda run -n advandeb pytest tests/test_traversal_options.py -v
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.database.arango_client import ArangoDatabase
from advandeb_kb.services.graph_expansion_service import GraphExpansionService

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "advandeb_kb"

EXPECTED_OPTIONS = "{uniqueVertices:'global',order:'bfs'}"

# OPTIONS clause in AQL source or in an f-string template ({{ ... }}).
_OPTIONS_RE = re.compile(r"OPTIONS\s*\{\{?([^{}]*)\}")


class RecordingArango(ArangoDatabase):
    """ArangoDatabase whose aql() records the query instead of running it,
    and answers with ``rows`` (empty by default)."""

    def __init__(self, rows=None) -> None:
        super().__init__(url="http://unused", db_name="unused",
                         username="unused", password="unused")
        self.queries: list[str] = []
        self.bind_vars: list[dict] = []
        self.rows = rows or []

    def aql(self, query, bind_vars=None):
        self.queries.append(query)
        self.bind_vars.append(bind_vars or {})
        return self.rows


def _options(aql: str) -> str:
    match = _OPTIONS_RE.search(aql)
    assert match, f"no OPTIONS clause in:\n{aql}"
    return "{" + re.sub(r"\s+", "", match.group(1)) + "}"


# ------------------------------------------------------------------
# Generated AQL at each traversal call site
# ------------------------------------------------------------------

def test_traverse_graph_uses_bfs_order():
    db = RecordingArango()
    GraphExpansionService(db)._traverse_graph(
        ["facts/1", "facts/2"], "support_graph", "OUTBOUND", 1, 1, 10
    )
    assert len(db.queries) == 1
    assert _options(db.queries[0]) == EXPECTED_OPTIONS


def test_citation_chain_uses_bfs_order():
    db = RecordingArango()
    GraphExpansionService(db).get_citation_chain("doc_abc", max_depth=3)
    assert len(db.queries) == 1
    assert _options(db.queries[0]) == EXPECTED_OPTIONS


def test_arango_client_traverse_uses_bfs_order():
    db = RecordingArango()
    db.traverse("documents/doc_abc", "knowledge_graph", "OUTBOUND", 1, 2, 10)
    assert len(db.queries) == 1
    assert _options(db.queries[0]) == EXPECTED_OPTIONS


# ------------------------------------------------------------------
# _traverse_graph: one query for all starts, still per-start semantics
# ------------------------------------------------------------------

def _paren_depth(aql: str, pos: int) -> int:
    return aql.count("(", 0, pos) - aql.count(")", 0, pos)


def test_traverse_graph_sends_one_query_for_all_starts():
    starts = [f"facts/{i}" for i in range(2000)]
    db = RecordingArango()
    GraphExpansionService(db)._traverse_graph(
        starts, "support_graph", "OUTBOUND", 1, 1, 10
    )
    assert len(db.queries) == 1
    assert db.bind_vars[0] == {
        "starts": starts, "graph": "support_graph", "limit": 10,
    }


def test_traverse_graph_limit_and_uniqueness_stay_per_start():
    # The traversal and its LIMIT sit in a subquery that runs once per
    # start. A LIMIT outside it would cap all starts together, and one
    # traversal over all starts would share one global-uniqueness set.
    db = RecordingArango()
    GraphExpansionService(db)._traverse_graph(
        ["documents/a", "documents/b"], "knowledge_graph", "OUTBOUND", 1, 2, 50
    )
    aql = db.queries[0]
    loop = re.search(r"FOR\s+(\w+)\s+IN\s+@starts\b", aql)
    assert loop, aql
    traversal = re.search(
        rf"FOR\s+\w+(?:\s*,\s*\w+)*\s+IN\s+1\.\.2\s+OUTBOUND\s+{loop.group(1)}"
        rf"\s+GRAPH\s+@graph\b",
        aql,
    )
    assert traversal and traversal.start() > loop.end(), aql
    depth = _paren_depth(aql, traversal.start())
    assert depth >= 1, f"traversal is not in a per-start subquery:\n{aql}"
    limits = [m.start() for m in re.finditer(r"\bLIMIT\b", aql)]
    assert limits, aql
    for pos in limits:
        assert pos > traversal.start() and _paren_depth(aql, pos) == depth, (
            f"LIMIT is not inside the per-start subquery:\n{aql}"
        )


def test_traverse_graph_without_starts_sends_nothing():
    db = RecordingArango()
    out = GraphExpansionService(db)._traverse_graph([], "support_graph")
    assert out == {"vertices": [], "path_steps": []}
    assert db.queries == []


def test_traverse_graph_result_shape_unchanged():
    def sf(key):
        return {"_id": f"stylized_facts/{key}", "_key": key, "statement": key}

    def edge(key, frm, to):
        return {"_id": f"sf_support/{key}", "_key": key, "_rev": "r",
                "_from": frm, "_to": to,
                "relation_type": "supports", "confidence": 0.9}

    # As the batched query returns them: by start, then in BFS order.
    rows = [
        {"vertex": sf("1"), "edge": edge("e1", "facts/1", "stylized_facts/1")},
        {"vertex": sf("2"), "edge": edge("e2", "facts/1", "stylized_facts/2")},
        {"vertex": sf("1"), "edge": edge("e3", "facts/2", "stylized_facts/1")},
        {"vertex": sf("3"), "edge": {"_from": "facts/2", "_to": "stylized_facts/3"}},
        {"vertex": sf("4"), "edge": None},
    ]
    out = GraphExpansionService(RecordingArango(rows))._traverse_graph(
        ["facts/1", "facts/2"], "support_graph", "OUTBOUND", 1, 1, 10
    )
    # Vertices: deduplicated across starts, first-seen order.
    assert [v["_id"] for v in out["vertices"]] == [
        "stylized_facts/1", "stylized_facts/2", "stylized_facts/3", "stylized_facts/4",
    ]
    attrs = {"relation_type": "supports", "confidence": 0.9}
    # Path steps: one per edge, not deduplicated, as before.
    assert out["path_steps"] == [
        {"from_id": "facts/1", "to_id": "stylized_facts/1",
         "edge_type": "sf_support", "edge_attrs": attrs},
        {"from_id": "facts/1", "to_id": "stylized_facts/2",
         "edge_type": "sf_support", "edge_attrs": attrs},
        {"from_id": "facts/2", "to_id": "stylized_facts/1",
         "edge_type": "sf_support", "edge_attrs": attrs},
        {"from_id": "facts/2", "to_id": "stylized_facts/3",
         "edge_type": "support_graph", "edge_attrs": {}},
    ]


def test_traverse_graph_failure_returns_empty_result():
    class FailingArango(RecordingArango):
        def aql(self, query, bind_vars=None):
            super().aql(query, bind_vars)
            raise RuntimeError("boom")

    db = FailingArango()
    out = GraphExpansionService(db)._traverse_graph(
        ["facts/1", "facts/2"], "support_graph"
    )
    assert out == {"vertices": [], "path_steps": []}
    assert len(db.queries) == 1


def test_expand_from_chunks_round_trips_do_not_grow_with_facts():
    def run(n_facts: int) -> RecordingArango:
        db = RecordingArango()
        svc = GraphExpansionService(db)
        # Lookups stubbed out: only the traversals reach the database.
        svc._chunk_ids_to_arango_keys = lambda ids: ["d1_chunk_0", "d2_chunk_0"]
        svc._fetch_vertices = lambda col, keys: [
            {"_key": k, "document_id": k.split("_")[0]} for k in keys
        ]
        svc._fetch_by_field = lambda col, field, values: []
        svc._get_facts_for_documents = lambda ids: [
            {"_key": str(i), "document_id": "d1"} for i in range(n_facts)
        ]
        svc.expand_from_chunks(["d1_chunk_0", "d2_chunk_0"], max_hops=2)
        return db

    few, many = run(3), run(5000)
    # One query each for chunk_graph, support_graph, knowledge_graph.
    assert len(few.queries) == len(many.queries) == 3
    support = [b for b in many.bind_vars if b["graph"] == "support_graph"]
    assert len(support) == 1 and len(support[0]["starts"]) == 5000


# ------------------------------------------------------------------
# Guard for call sites added later
# ------------------------------------------------------------------

def test_no_global_uniqueness_without_bfs_or_weighted_order():
    offenders = []
    checked = 0
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "bfsMode" in source:
            offenders.append(f"{path.name}: bfsMode is not an ArangoDB option")
        for match in _OPTIONS_RE.finditer(source):
            opts = re.sub(r"\s+", "", match.group(1))
            if "uniqueVertices:'global'" not in opts:
                continue
            checked += 1
            if not re.search(r"order:'(bfs|weighted)'", opts):
                line = source.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.name}:{line}: {{{opts}}}")
    # Non-vacuous: the three known traversals must have been seen.
    assert checked >= 3, f"scanner found only {checked} traversals"
    assert not offenders, "\n".join(offenders)
