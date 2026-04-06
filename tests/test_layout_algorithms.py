"""
Unit tests for schema-specific layout algorithms.

These tests run entirely in-process — no MongoDB or network access required.
They verify that each layout function correctly sets x, y, z, x2d, y2d on
node dicts in-place.
"""
import sys
import os

# Allow importing from the knowledge-builder package without a full install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "knowledge-builder"))

from advandeb_kb.services.visualization_service import (
    _layout_sf_support,
    _layout_taxonomical,
    _layout_citation,
    _layout_knowledge_graph,
    _layout_physiological,
    _dispatch_layout,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_nodes(types):
    """Return a minimal list of node dicts with _id and node_type set."""
    return [{"_id": str(i), "node_type": t, "properties": {}} for i, t in enumerate(types)]


def assert_coords(nodes):
    """Assert that every node has numeric x, y, z, x2d, y2d."""
    for n in nodes:
        for field in ("x", "y", "z", "x2d", "y2d"):
            assert field in n, f"Field '{field}' missing on node {n['_id']}"
            assert isinstance(n[field], (int, float)), (
                f"Field '{field}' on node {n['_id']} is not numeric: {n[field]!r}"
            )


# ---------------------------------------------------------------------------
# Task 5 — sf_support
# ---------------------------------------------------------------------------

def test_sf_support_layout_basic():
    nodes = make_nodes(["document"] * 5 + ["fact"] * 10 + ["stylized_fact"] * 3)
    edges = []
    _layout_sf_support(nodes, edges)

    docs = [n for n in nodes if n["node_type"] == "document"]
    facts = [n for n in nodes if n["node_type"] == "fact"]
    sfs = [n for n in nodes if n["node_type"] == "stylized_fact"]

    assert_coords(nodes)

    # All documents at same y2d
    assert len({n["y2d"] for n in docs}) == 1, "Document y2d values should all be equal"
    # All facts at same y2d
    assert len({n["y2d"] for n in facts}) == 1, "Fact y2d values should all be equal"
    # Stylized facts higher than documents
    assert sfs[0]["y2d"] > docs[0]["y2d"], "SFs should be higher than documents on y2d axis"


def test_sf_support_layout_no_edges():
    """Layout should run without raising even with zero edges."""
    nodes = make_nodes(["stylized_fact"] * 5)
    _layout_sf_support(nodes, [])
    assert_coords(nodes)


def test_sf_support_layout_single_node():
    nodes = make_nodes(["fact"])
    _layout_sf_support(nodes, [])
    assert_coords(nodes)


# ---------------------------------------------------------------------------
# Task 6 — taxonomical
# ---------------------------------------------------------------------------

def test_taxonomical_layout_chain():
    """A simple chain: 0 is_child_of 1 is_child_of 2 (root=2)."""
    nodes = [
        {"_id": "0", "node_type": "taxon", "properties": {}},
        {"_id": "1", "node_type": "taxon", "properties": {}},
        {"_id": "2", "node_type": "taxon", "properties": {}},
    ]
    edges = [
        {"_id": "e0", "edge_type": "is_child_of", "source_node_id": "0", "target_node_id": "1"},
        {"_id": "e1", "edge_type": "is_child_of", "source_node_id": "1", "target_node_id": "2"},
    ]
    _layout_taxonomical(nodes, edges)
    assert_coords(nodes)

    node_by_id = {n["_id"]: n for n in nodes}
    # Root (2) should be at y2d=0; depth increases downward (negative y)
    assert node_by_id["2"]["y2d"] == 0.0, "Root should be at y2d=0"
    assert node_by_id["1"]["y2d"] < 0, "Level-1 node should be below root"
    assert node_by_id["0"]["y2d"] < node_by_id["1"]["y2d"], "Leaf should be below level-1"


def test_taxonomical_layout_no_edges():
    """Fallback when no is_child_of edges exist — should not raise."""
    nodes = make_nodes(["taxon"] * 5)
    _layout_taxonomical(nodes, [])
    assert_coords(nodes)


# ---------------------------------------------------------------------------
# Task 7 — citation
# ---------------------------------------------------------------------------

def test_citation_layout_basic():
    nodes = make_nodes(["document"] * 8)
    # Create a ring of edges so community detection has something to work with
    edges = [
        {"_id": f"e{i}", "source_node_id": str(i), "target_node_id": str((i + 1) % 8)}
        for i in range(8)
    ]
    _layout_citation(nodes, edges)
    assert_coords(nodes)


def test_citation_layout_no_edges():
    nodes = make_nodes(["document"] * 4)
    _layout_citation(nodes, [])
    assert_coords(nodes)


def test_citation_layout_empty():
    """Empty node list should not raise."""
    _layout_citation([], [])


# ---------------------------------------------------------------------------
# Task 8 — knowledge_graph
# ---------------------------------------------------------------------------

def test_knowledge_graph_layout_with_clusters():
    nodes = []
    for i in range(20):
        cid = f"cluster_{i // 5}"
        nodes.append({"_id": str(i), "node_type": "fact", "cluster_id": cid, "properties": {"cluster_id": cid}})
    edges = [
        {"_id": f"e{i}", "source_node_id": str(i), "target_node_id": str(i + 1)}
        for i in range(19)
    ]
    _layout_knowledge_graph(nodes, edges)
    assert_coords(nodes)


def test_knowledge_graph_layout_no_clusters():
    """Nodes without cluster_id should default to 'default' cluster."""
    nodes = make_nodes(["fact"] * 6)
    _layout_knowledge_graph(nodes, [])
    assert_coords(nodes)


# ---------------------------------------------------------------------------
# Task 9 — physiological_process
# ---------------------------------------------------------------------------

def test_physiological_layout_basic():
    nodes = make_nodes(["stylized_fact"] * 5 + ["taxon"] * 3)
    edges = [
        {"_id": "e0", "source_node_id": "0", "target_node_id": "5", "weight": 0.8},
        {"_id": "e1", "source_node_id": "1", "target_node_id": "6", "weight": 0.5},
    ]
    _layout_physiological(nodes, edges)
    assert_coords(nodes)


def test_physiological_layout_empty():
    _layout_physiological([], [])


# ---------------------------------------------------------------------------
# Task 4 — _dispatch_layout
# ---------------------------------------------------------------------------

def test_dispatch_routes_correctly():
    """Dispatcher should select the right algorithm per schema name."""
    for schema_name in ("sf_support", "taxonomical", "citation", "knowledge_graph", "physiological_process"):
        nodes = make_nodes(["fact"] * 3)
        _dispatch_layout(nodes, [], schema_name)
        assert_coords(nodes), f"Dispatch for '{schema_name}' did not set coords"


def test_dispatch_unknown_schema_uses_legacy():
    """Unknown schema name should fall back to legacy layout without raising."""
    nodes = make_nodes(["fact"] * 3)
    _dispatch_layout(nodes, [], "nonexistent_schema")
    # Legacy layout sets x/y/z but not necessarily x2d/y2d
    for n in nodes:
        for field in ("x", "y", "z"):
            assert field in n, f"Legacy layout missing '{field}' for node {n['_id']}"
