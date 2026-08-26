"""
Schema-specific 2D + 3D graph layout functions.

Pure-Python / NetworkX — no database access.  Called from
``GraphQueryService.get_graph_with_layout`` and ``get_overview`` via
``run_in_executor`` so they don't block the event loop.

Each ``_layout_*`` function mutates the input nodes in place, setting
``x``, ``y``, ``z`` (3D) and ``x2d``, ``y2d`` (2D) on every dict.

Public surface (re-exported from ``graph_query_service``):
    _apply_layout
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Callable, Dict, List, Optional

import networkx as nx


SCHEMA_LAYOUT_MAP: Dict[str, Any] = {}   # populated at module bottom


# ---------------------------------------------------------------------------
# Spring-iteration tapering
# ---------------------------------------------------------------------------
#
# ``nx.spring_layout`` costs roughly O(N^1.57) per call at a fixed iteration
# count, and is linear in the iteration count on top of that. Measured on the
# dev box at 60 iterations: 1k nodes = 3.5s, 2k = 10.4s, 4k = 31.0s. Real
# rebuilds were far worse — sf_support (one 18k-node ``fact`` cluster) took
# 546s, knowledge_graph 489s — which is long enough that a rebuild kicked off
# from the UI looks like a hang, and long enough that back-to-back rebuilds
# from ``graph_rebuild_queue`` can pile up.
#
# Big clusters don't need the full iteration budget: past a few thousand nodes
# the extra passes are refining positions well below what anyone can see at the
# zoom level a 20k-node graph is viewed at. So spend the full budget on small
# clusters, where each iteration is cheap and visibly improves the picture, and
# taper logarithmically towards a floor as clusters grow.
ITER_FULL_BELOW = 2_000      # clusters up to this size get the full budget
ITER_FLOOR_ABOVE = 20_000    # clusters this size or larger get ITER_FLOOR
ITER_FLOOR = 15              # minimum passes, however large the cluster


def _taper_iterations(n_in_cluster: int, budget: int) -> int:
    """Spring iterations to spend on a cluster of ``n_in_cluster`` nodes.

    Returns ``budget`` unchanged below ``ITER_FULL_BELOW`` — so small graphs,
    including every graph in the test suite, lay out exactly as before — then
    interpolates log-linearly down to ``ITER_FLOOR`` at ``ITER_FLOOR_ABOVE``.
    """
    if budget <= ITER_FLOOR or n_in_cluster <= ITER_FULL_BELOW:
        return budget
    if n_in_cluster >= ITER_FLOOR_ABOVE:
        return ITER_FLOOR
    # Log-linear because the cost curve is a power law: equal ratios of cluster
    # size cost equal multiples, so they should shed equal shares of the budget.
    t = math.log(n_in_cluster / ITER_FULL_BELOW) / math.log(
        ITER_FLOOR_ABOVE / ITER_FULL_BELOW
    )
    return max(ITER_FLOOR, int(round(budget + t * (ITER_FLOOR - budget))))


def _apply_layout(
    nodes: List[Dict],
    edges: List[Dict],
    schema_name: str,
) -> None:
    """Blocking layout dispatch (called in thread executor).

    Routes to the schema-specific layout function; falls back to generic
    spring layout for unrecognised schema names.
    """
    fn = SCHEMA_LAYOUT_MAP.get(schema_name, _layout_generic)
    fn(nodes, edges)


# ---------------------------------------------------------------------------
# Unified clustered-spring helper (used by every non-tree layout below)
# ---------------------------------------------------------------------------

def _clustered_spring_layout(
    nodes: List[Dict],
    edges: List[Dict],
    cluster_fn: Callable[[Dict], Optional[str]],
    *,
    intra_iterations: int = 60,
    intra_seed: int = 42,
    scale_per_node: float = 18.0,
    min_cluster_scale: float = 60.0,
    cluster_padding: float = 1.15,
) -> None:
    """
    Unified clustered-spring layout.

      1. Partition nodes into clusters via ``cluster_fn(node) -> str``.
      2. Run a weighted ``nx.spring_layout`` INSIDE each cluster — edge weights
         drive intra-cluster distance.  Larger clusters get a larger
         coordinate scale so dense groups don't compress to a single point,
         and a smaller share of ``intra_iterations`` (see ``_taper_iterations``)
         so a single huge cluster can't dominate the rebuild time.
      3. Place cluster centroids by greedy golden-angle packing: the largest
         cluster takes the centre, each next one goes out along the golden
         angle until it clears every cluster already placed.
         ``cluster_padding`` is the centre-distance multiplier on the sum of
         two clusters' radii — 1.0 means exactly touching, 1.15 leaves a
         modest gap. Values much above ~1.5 push clusters so far apart that
         the edges between them dominate the picture.
      4. Final node position = cluster_centroid + intra_cluster_offset.
      5. 3D Z coordinate = (cluster_index * 80) - centroid, so clusters
         stack along Z too (helps disambiguate in 3D view) but X/Y still
         carry all the semantic information.

    Mutates the input nodes in place.
    """
    if not nodes:
        return

    # ---- 1. Partition into clusters ----
    clusters: Dict[str, List[Dict]] = {}
    for n in nodes:
        cid = cluster_fn(n)
        if cid is None:
            continue
        clusters.setdefault(str(cid), []).append(n)

    if not clusters:
        return

    # ---- 2. Build the full graph once ----
    id_set = {n["_id"] for n in nodes}
    G = nx.Graph()
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src = e.get("source_node_id")
        tgt = e.get("target_node_id")
        if not (src and tgt) or src == tgt:
            continue
        if src not in id_set or tgt not in id_set:
            continue
        # Edge weight: clamp to a tiny positive number so weight=0 still
        # allows the spring solver to converge.
        w_raw = e.get("weight")
        try:
            w = float(w_raw) if w_raw is not None else 1.0
        except (TypeError, ValueError):
            w = 1.0
        if w <= 0.0:
            w = 0.01
        if G.has_edge(src, tgt):
            # Combine parallel edges by taking the max weight (stronger pull wins).
            G[src][tgt]["weight"] = max(G[src][tgt]["weight"], w)
        else:
            G.add_edge(src, tgt, weight=w)

    # ---- 3. Per-cluster spring layout ----
    cluster_order = list(clusters.keys())
    cluster_scales: Dict[str, float] = {}
    intra_pos: Dict[str, tuple] = {}

    for cid in cluster_order:
        cnodes = clusters[cid]
        n_in_cluster = len(cnodes)
        cluster_scale = max(min_cluster_scale, scale_per_node * math.sqrt(n_in_cluster))
        cluster_scales[cid] = cluster_scale

        if n_in_cluster == 1:
            # Singleton — sits at the cluster centroid.
            intra_pos[cnodes[0]["_id"]] = (0.0, 0.0)
            continue

        sub_ids = [n["_id"] for n in cnodes]
        sub = G.subgraph(sub_ids)
        k_sub = max(0.3, 2.0 / math.sqrt(n_in_cluster))

        sub_pos: Dict[str, tuple]
        try:
            sub_pos = nx.spring_layout(
                sub,
                weight="weight",
                k=k_sub,
                iterations=_taper_iterations(n_in_cluster, intra_iterations),
                seed=intra_seed,
                scale=cluster_scale,
            )
        except Exception:
            sub_pos = {}

        # Fallback for any node that ended up NaN or missing.
        for i, nid in enumerate(sub_ids):
            xy = sub_pos.get(nid)
            if (
                xy is None
                or not math.isfinite(float(xy[0]))
                or not math.isfinite(float(xy[1]))
            ):
                angle = 2 * math.pi * i / max(n_in_cluster, 1)
                jitter_r = cluster_scale * 0.5
                sub_pos[nid] = (
                    jitter_r * math.cos(angle),
                    jitter_r * math.sin(angle),
                )

        intra_pos.update({nid: (float(xy[0]), float(xy[1])) for nid, xy in sub_pos.items()})

    # ---- 4. Centroid placement: greedy golden-angle packing ----
    #
    # The largest cluster takes the centre; every other cluster goes out along
    # the golden angle only as far as it needs to clear what is already placed.
    #
    # The previous version put cluster i at `base * sqrt(i + 1)` — note the +1,
    # so *no* cluster ever sat at the origin — with `base` driven by the single
    # largest cluster's radius. On sf_support that meant one 18k-node cluster
    # (radius ~2400) flung the two ~600-radius clusters 5,500 and 9,300 units
    # out, leaving the middle of the canvas empty. What you saw was 49k edges
    # bundling across a void, not three clusters.
    golden_angle = math.pi * (3 - math.sqrt(5))  # ~2.39996

    # Descending by radius: the biggest cluster is the one worth the centre, and
    # placing large before small means later clearance checks rarely iterate.
    placement_order = sorted(cluster_order, key=lambda c: -cluster_scales[c])

    centroids: Dict[str, tuple] = {}
    placed: List[tuple] = []  # (x, y, radius) of clusters already positioned

    for i, cid in enumerate(placement_order):
        radius = cluster_scales[cid]
        if i == 0:
            centroids[cid] = (0.0, 0.0)
            placed.append((0.0, 0.0, radius))
            continue

        theta = i * golden_angle
        dx, dy = math.cos(theta), math.sin(theta)
        step = max(radius * 0.25, min_cluster_scale * 0.5)
        r = radius
        x = y = 0.0
        # Walk outwards until this cluster clears every placed one. Bounded by
        # the cluster count (tens at most), so the loop is cheap.
        while True:
            x, y = r * dx, r * dy
            if all(
                math.hypot(x - px, y - py) >= (radius + pr) * cluster_padding
                for px, py, pr in placed
            ):
                break
            r += step

        centroids[cid] = (x, y)
        placed.append((x, y, radius))

    # ---- 5. Z slabs (centred on 0) ----
    n_clusters = len(cluster_order)
    z_offset = n_clusters * 40
    z_for_cluster: Dict[str, float] = {
        cid: (i * 80) - z_offset for i, cid in enumerate(cluster_order)
    }

    # ---- 6. Write coordinates back ----
    # Build node -> cluster map for assignment.
    node_to_cluster: Dict[str, str] = {}
    for cid, cnodes in clusters.items():
        for n in cnodes:
            node_to_cluster[n["_id"]] = cid

    for n in nodes:
        nid = n["_id"]
        cid = node_to_cluster.get(nid)
        if cid is None:
            # Node was filtered out by cluster_fn returning None — give it
            # a deterministic origin so the frontend doesn't see NaN.
            n["x2d"] = 0.0
            n["y2d"] = 0.0
            n["x"]   = 0.0
            n["y"]   = 0.0
            n["z"]   = 0.0
            continue
        cx, cy = centroids[cid]
        lx, ly = intra_pos.get(nid, (0.0, 0.0))
        # Deterministic Z jitter within the slab.
        z_jitter = (hash(nid) % 40) - 20
        z = z_for_cluster[cid] + z_jitter
        n["x2d"] = round(cx + lx, 1)
        n["y2d"] = round(cy + ly, 1)
        n["x"]   = round(cx + lx, 1)
        n["y"]   = round(cy + ly, 1)
        n["z"]   = round(float(z), 1)


# ---------------------------------------------------------------------------
# generic: community-detection fallback
# ---------------------------------------------------------------------------

def _layout_generic(nodes: List[Dict], edges: List[Dict]) -> None:
    """Community-clustered spring layout (fallback for unknown schemas)."""
    if not nodes:
        return
    G = nx.Graph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src != tgt and src in id_set and tgt in id_set:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    try:
        communities = list(nx.community.greedy_modularity_communities(G))
    except Exception:
        communities = [set(G.nodes)]
    node_community: Dict[str, int] = {}
    for i, comm in enumerate(communities):
        for nid in comm:
            node_community[nid] = i

    def cluster_fn(n: Dict) -> str:
        return f"c{node_community.get(n['_id'], 0)}"

    _clustered_spring_layout(nodes, edges, cluster_fn)


# ---------------------------------------------------------------------------
# sf_support: cluster by node_type
# ---------------------------------------------------------------------------

def _layout_sf_support(nodes: List[Dict], edges: List[Dict]) -> None:
    """Cluster by node_type (document / fact / stylized_fact / …)."""

    def cluster_fn(n: Dict) -> str:
        return f"sf:{n.get('node_type', 'other')}"

    _clustered_spring_layout(nodes, edges, cluster_fn, cluster_padding=1.2)


# ---------------------------------------------------------------------------
# taxonomical: rooted tree  (UNCHANGED — trees are the right shape here)
# ---------------------------------------------------------------------------

def _layout_taxonomical(nodes: List[Dict], edges: List[Dict]) -> None:
    """Radial dendrogram: root at the centre, each rank one ring further out.

    Angular span is divided by leaf count, so sibling subtrees get room in
    proportion to how much they contain and no two branches overlap. The result
    is roughly circular, which matters — the previous tidy-tree layout laid
    depth on Y and cumulative leaf offsets on X, giving bounds tens of millions
    of units wide and a few thousand tall. Nothing can render that.

    Handles a forest (several roots), which the scoped taxonomy can produce when
    the lineage of a studied taxon reaches a tax_id absent from the import.
    """
    id_set = {n["_id"] for n in nodes}
    if not id_set:
        return

    child_to_parent: Dict[str, str] = {}
    children_map: Dict[str, List[str]] = {}
    for e in edges:
        if e.get("edge_type") != "is_child_of":
            continue
        child = e.get("source_node_id")
        parent = e.get("target_node_id")
        if not child or not parent or child == parent:
            continue
        if child in id_set and parent in id_set and child not in child_to_parent:
            child_to_parent[child] = parent
            children_map.setdefault(parent, []).append(child)

    if not child_to_parent:
        _layout_generic(nodes, edges)
        return

    roots = sorted(nid for nid in id_set if nid not in child_to_parent)
    if not roots:
        # Every node has a parent — the graph is cyclic. Break the cycle by
        # picking a deterministic entry point rather than looping forever.
        roots = [min(id_set)]

    # A lone root sits at the centre (ring 0). Several roots have to share the
    # innermost ring instead, so push everything out by one.
    depth_offset = 0 if len(roots) == 1 else 1

    # ---- Depths, BFS from every root (iterative; lineages can be deep) ----
    depths: Dict[str, int] = {}
    queue = deque((r, depth_offset) for r in roots)
    for r in roots:
        depths[r] = depth_offset
    while queue:
        nid, depth = queue.popleft()
        for child in children_map.get(nid, []):
            if child not in depths:
                depths[child] = depth + 1
                queue.append((child, depth + 1))

    # ---- Leaf counts, iterative post-order ----
    leaf_counts: Dict[str, int] = {}
    for root in roots:
        stack = [(root, False)]
        while stack:
            nid, expanded = stack.pop()
            children = children_map.get(nid, [])
            if not children:
                leaf_counts[nid] = 1
            elif expanded:
                leaf_counts[nid] = sum(leaf_counts.get(c, 1) for c in children)
            else:
                stack.append((nid, True))
                for c in children:
                    if c not in leaf_counts:
                        stack.append((c, False))

    # ---- Angular wedges, iterative pre-order ----
    TWO_PI = 2 * math.pi
    RING = 130.0

    angles: Dict[str, float] = {}
    total_leaves = sum(leaf_counts.get(r, 1) for r in roots) or 1

    cursor = 0.0
    stack: List[tuple] = []
    for root in roots:
        span = TWO_PI * leaf_counts.get(root, 1) / total_leaves
        stack.append((root, cursor, cursor + span))
        cursor += span

    while stack:
        nid, start, end = stack.pop()
        angles[nid] = (start + end) / 2
        children = children_map.get(nid, [])
        if not children:
            continue
        span = end - start
        own_leaves = leaf_counts.get(nid, 1) or 1
        child_cursor = start
        for child in children:
            child_span = span * leaf_counts.get(child, 1) / own_leaves
            stack.append((child, child_cursor, child_cursor + child_span))
            child_cursor += child_span

    # ---- Write coordinates ----
    # Anything unreachable from a root (only possible via a cycle) goes on an
    # outer ring so it stays visible instead of piling up at the origin.
    orphan_depth = max(depths.values(), default=0) + 1
    orphans = [nid for nid in sorted(id_set) if nid not in depths]

    for i, nid in enumerate(orphans):
        depths[nid] = orphan_depth
        angles[nid] = TWO_PI * i / max(len(orphans), 1)

    for n in nodes:
        nid = n["_id"]
        depth = depths.get(nid, 0)
        theta = angles.get(nid, 0.0)
        r = depth * RING
        n["x2d"] = round(r * math.cos(theta), 1)
        n["y2d"] = round(r * math.sin(theta), 1)
        n["x"]   = n["x2d"]
        n["y"]   = n["y2d"]
        # Lift each ring in Z so the 3D view reads as a cone, not a flat disc.
        n["z"]   = round(float(depth) * 40.0, 1)


# ---------------------------------------------------------------------------
# citation: community-clustered
# ---------------------------------------------------------------------------

def _layout_citation(nodes: List[Dict], edges: List[Dict]) -> None:
    """Community-clustered layout for citation graph."""
    G = nx.Graph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set and src != tgt:
            G.add_edge(src, tgt)
    try:
        communities = list(nx.community.greedy_modularity_communities(G))
    except Exception:
        communities = [set(G.nodes)]
    comm_map = {nid: i for i, comm in enumerate(communities) for nid in comm}

    def cluster_fn(n: Dict) -> str:
        return f"cit:{comm_map.get(n['_id'], 0)}"

    _clustered_spring_layout(nodes, edges, cluster_fn, cluster_padding=1.15)


# ---------------------------------------------------------------------------
# knowledge_graph: cluster_id grouping
# ---------------------------------------------------------------------------

def _layout_knowledge_graph(nodes: List[Dict], edges: List[Dict]) -> None:
    """Cluster by cluster_id (falls back to ``default`` bucket)."""

    def cluster_fn(n: Dict) -> str:
        return (
            n.get("cluster_id")
            or n.get("properties", {}).get("cluster_id")
            or "default"
        )

    _clustered_spring_layout(nodes, edges, cluster_fn, cluster_padding=1.15)


# ---------------------------------------------------------------------------
# physiological_process: cluster by node_type
# ---------------------------------------------------------------------------

def _layout_physiological(nodes: List[Dict], edges: List[Dict]) -> None:
    """Cluster by node_type for physiological-process schema."""

    def cluster_fn(n: Dict) -> str:
        return f"phys:{n.get('node_type', 'other')}"

    _clustered_spring_layout(nodes, edges, cluster_fn, cluster_padding=1.15)


# ---------------------------------------------------------------------------
# chatbot: cluster by node_type
# ---------------------------------------------------------------------------

def _layout_chatbot(nodes: List[Dict], edges: List[Dict]) -> None:
    """Cluster by node_type for chatbot schema."""

    def cluster_fn(n: Dict) -> str:
        return f"chat:{n.get('node_type', 'other')}"

    _clustered_spring_layout(nodes, edges, cluster_fn, cluster_padding=1.3)


# ---------------------------------------------------------------------------
# Dispatch map (populated last so all functions are defined)
# ---------------------------------------------------------------------------

SCHEMA_LAYOUT_MAP["sf_support"]            = _layout_sf_support
SCHEMA_LAYOUT_MAP["taxonomical"]           = _layout_taxonomical
SCHEMA_LAYOUT_MAP["citation"]              = _layout_citation
SCHEMA_LAYOUT_MAP["knowledge_graph"]       = _layout_knowledge_graph
SCHEMA_LAYOUT_MAP["physiological_process"] = _layout_physiological
SCHEMA_LAYOUT_MAP["chatbot"]               = _layout_chatbot
