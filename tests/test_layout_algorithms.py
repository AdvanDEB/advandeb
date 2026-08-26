"""
Unit tests for schema-specific layout algorithms.

These tests run entirely in-process — no MongoDB or network access required.
They verify that each layout function correctly sets x, y, z, x2d, y2d on
node dicts in-place.
"""
import math
import sys
import os

# Allow importing from the knowledge-builder package without a full install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "knowledge-builder"))

from advandeb_kb.services import graph_query_layouts as layouts
from advandeb_kb.services.graph_query_layouts import (
    _layout_sf_support,
    _layout_taxonomical,
    _layout_citation,
    _layout_knowledge_graph,
    _layout_physiological,
    _apply_layout as _dispatch_layout,
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

    # sf_support groups by node_type via the clustered-spring layout: each type
    # gets its own centroid on a Fibonacci spiral, with members spread around it.
    # (This replaced an earlier layered layout that put each type on a fixed y2d.)
    def centroid(group):
        return (
            sum(n["x2d"] for n in group) / len(group),
            sum(n["y2d"] for n in group) / len(group),
        )

    def spread(group, centre):
        return max(math.hypot(n["x2d"] - centre[0], n["y2d"] - centre[1]) for n in group)

    centres = {"document": centroid(docs), "fact": centroid(facts), "stylized_fact": centroid(sfs)}
    groups = {"document": docs, "fact": facts, "stylized_fact": sfs}

    for a, b in (("document", "fact"), ("document", "stylized_fact"), ("fact", "stylized_fact")):
        separation = math.hypot(centres[a][0] - centres[b][0], centres[a][1] - centres[b][1])
        assert separation > spread(groups[a], centres[a]), (
            f"{a} cluster is not separated from {b}"
        )


def assert_clusters_separated(nodes):
    """Each node_type's members must sit closer to their own centroid than to another's."""
    groups = {}
    for n in nodes:
        groups.setdefault(n["node_type"], []).append(n)

    centres = {
        t: (
            sum(n["x2d"] for n in g) / len(g),
            sum(n["y2d"] for n in g) / len(g),
        )
        for t, g in groups.items()
    }

    for t, g in groups.items():
        own = centres[t]
        radius = max(math.hypot(n["x2d"] - own[0], n["y2d"] - own[1]) for n in g)
        for other, centre in centres.items():
            if other == t:
                continue
            separation = math.hypot(own[0] - centre[0], own[1] - centre[1])
            assert separation > radius, f"{t} cluster is not separated from {other}"


def test_clustered_layout_puts_largest_cluster_at_the_centre():
    """One dominant cluster plus small ones must not leave the middle empty.

    The centroid spiral used to start at `base * sqrt(i + 1)`, so no cluster
    ever sat at the origin, and `base` came from the largest cluster's radius.
    A graph with one big cluster therefore rendered as a ring of clusters with
    all their edges bundling across a void in the centre.
    """
    nodes = make_nodes(["fact"] * 900 + ["document"] * 40 + ["stylized_fact"] * 40)
    _layout_sf_support(nodes, [])
    assert_coords(nodes)

    facts = [n for n in nodes if n["node_type"] == "fact"]
    fx = sum(n["x2d"] for n in facts) / len(facts)
    fy = sum(n["y2d"] for n in facts) / len(facts)
    fact_radius = max(math.hypot(n["x2d"] - fx, n["y2d"] - fy) for n in facts)
    # Spring output isn't perfectly balanced, so compare against the cluster's
    # own size rather than demanding an exact zero.
    assert math.hypot(fx, fy) < fact_radius * 0.05, (
        "Largest cluster should sit at the centre of the layout"
    )

    # And the whole layout should be mostly cluster, not mostly gap.
    xs = [n["x2d"] for n in nodes]
    width = max(xs) - min(xs)
    fact_diameter = 2 * fact_radius
    assert fact_diameter / width > 0.5, (
        f"Dominant cluster spans only {fact_diameter / width:.0%} of the layout — "
        "clusters are being flung too far apart"
    )


# ---------------------------------------------------------------------------
# Spring-iteration tapering
# ---------------------------------------------------------------------------

def test_taper_leaves_small_clusters_at_full_budget():
    """Below the threshold nothing changes, so existing layouts are untouched."""
    for n in (1, 10, 500, layouts.ITER_FULL_BELOW):
        assert layouts._taper_iterations(n, 60) == 60


def test_taper_is_monotonic_and_bounded():
    """Iterations fall as clusters grow, and never below the floor."""
    sizes = [2_000, 3_000, 5_000, 10_000, 18_000, 20_000, 50_000]
    values = [layouts._taper_iterations(n, 60) for n in sizes]

    assert values == sorted(values, reverse=True), f"not monotonic: {values}"
    assert all(layouts.ITER_FLOOR <= v <= 60 for v in values), values
    assert layouts._taper_iterations(layouts.ITER_FLOOR_ABOVE, 60) == layouts.ITER_FLOOR
    # The 18k-node sf_support `fact` cluster is the case that made rebuilds
    # take ~9 minutes; it should shed most of its budget.
    assert layouts._taper_iterations(18_053, 60) < 20


def test_taper_never_raises_a_budget_below_the_floor():
    """A caller asking for fewer iterations than the floor keeps what it asked for."""
    assert layouts._taper_iterations(50_000, 10) == 10


def test_clusters_still_separate_when_tapering_is_active(monkeypatch):
    """Fewer iterations must not smear clusters into each other.

    Tapering only bites above ITER_FULL_BELOW, and a genuinely 20k-node graph is
    too slow for a unit test — so pull the thresholds down instead and lay out a
    small graph at the tapered floor.
    """
    monkeypatch.setattr(layouts, "ITER_FULL_BELOW", 10)
    monkeypatch.setattr(layouts, "ITER_FLOOR_ABOVE", 100)
    assert layouts._taper_iterations(200, 60) == layouts.ITER_FLOOR

    nodes = make_nodes(["fact"] * 200 + ["document"] * 60 + ["stylized_fact"] * 40)
    edges = [
        {"_id": f"e{i}", "source_node_id": str(i), "target_node_id": str(i + 1), "weight": 1.0}
        for i in range(199)
    ]
    _layout_sf_support(nodes, edges)
    assert_coords(nodes)
    assert_clusters_separated(nodes)


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

    def radius(nid):
        n = node_by_id[nid]
        return math.hypot(n["x2d"], n["y2d"])

    # Radial dendrogram: the root sits at the centre and each level out is one
    # ring further from it.
    assert radius("2") == 0.0, "Root should be at the centre"
    assert radius("1") > 0, "Level-1 node should sit on a ring outside the root"
    assert radius("0") > radius("1"), "Leaf should sit outside its parent"


def test_taxonomical_layout_no_edges():
    """Fallback when no is_child_of edges exist — should not raise."""
    nodes = make_nodes(["taxon"] * 5)
    _layout_taxonomical(nodes, [])
    assert_coords(nodes)


def test_taxonomical_layout_forest():
    """Several roots — the scoped taxonomy produces these when a studied taxon's
    lineage reaches a tax_id that is absent from the import."""
    nodes = make_nodes(["taxon"] * 4)
    edges = [
        {"_id": "e0", "edge_type": "is_child_of", "source_node_id": "1", "target_node_id": "0"},
        {"_id": "e1", "edge_type": "is_child_of", "source_node_id": "3", "target_node_id": "2"},
    ]
    _layout_taxonomical(nodes, edges)
    assert_coords(nodes)

    node_by_id = {n["_id"]: n for n in nodes}
    # With no single root to occupy the centre, every node lands on a ring and
    # the two roots must not be stacked on the same point.
    for nid in ("0", "2"):
        assert math.hypot(node_by_id[nid]["x2d"], node_by_id[nid]["y2d"]) > 0
    assert (node_by_id["0"]["x2d"], node_by_id["0"]["y2d"]) != (node_by_id["2"]["x2d"], node_by_id["2"]["y2d"])


def test_taxonomical_layout_bounds_are_not_degenerate():
    """A wide, shallow tree must stay roughly square.

    The previous tidy-tree layout put cumulative leaf offsets on X and depth on
    Y, so a real taxonomy came out tens of millions of units wide and a few
    thousand tall — an aspect ratio nothing can render.
    """
    nodes = make_nodes(["taxon"] * 201)
    edges = [
        {"_id": f"e{i}", "edge_type": "is_child_of", "source_node_id": str(i), "target_node_id": "0"}
        for i in range(1, 201)
    ]
    _layout_taxonomical(nodes, edges)
    assert_coords(nodes)

    xs = [n["x2d"] for n in nodes]
    ys = [n["y2d"] for n in nodes]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    assert width > 0 and height > 0
    assert 0.5 < width / height < 2.0, f"Aspect ratio {width / height} is not renderable"


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
