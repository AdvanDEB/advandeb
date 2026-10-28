"""
Pins the OPTIONS clause of every AQL graph traversal.

ArangoDB (3.12 here) rejects `uniqueVertices: 'global'` unless the traversal
order is 'bfs' or 'weighted': [HTTP 400][ERR 10]. The code used to send
`bfsMode: true`, which is not an ArangoDB option, so every traversal failed,
the failure was logged as a warning, and chat graph expansion silently
returned nothing.

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
    """ArangoDatabase whose aql() records the query instead of running it."""

    def __init__(self) -> None:
        super().__init__(url="http://unused", db_name="unused",
                         username="unused", password="unused")
        self.queries: list[str] = []

    def aql(self, query, bind_vars=None):
        self.queries.append(query)
        return []


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
    assert len(db.queries) == 2
    for aql in db.queries:
        assert _options(aql) == EXPECTED_OPTIONS


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
