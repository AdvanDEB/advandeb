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
    cluster_separation: float = 1.8,
) -> None:
    """
    Unified clustered-spring layout.

      1. Partition nodes into clusters via ``cluster_fn(node) -> str``.
      2. Run a weighted ``nx.spring_layout`` INSIDE each cluster — edge weights
         drive intra-cluster distance.  Larger clusters get a larger
         coordinate scale so dense groups don't compress to a single point.
      3. Place cluster centroids on a Fibonacci-spiral (well-separated,
         deterministic, no privileged angle).  Cluster size sets the
         per-cluster radius; ``cluster_separation`` controls the gap.
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
                iterations=intra_iterations,
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

    # ---- 4. Centroid placement on a Fibonacci spiral ----
    max_cluster_radius = max(cluster_scales.values(), default=min_cluster_scale)
    base_separation = cluster_separation * (max_cluster_radius + min_cluster_scale)
    golden_angle = math.pi * (3 - math.sqrt(5))  # ~2.39996

    centroids: Dict[str, tuple] = {}
    for i, cid in enumerate(cluster_order):
        if len(cluster_order) == 1:
            centroids[cid] = (0.0, 0.0)
            continue
        r = base_separation * math.sqrt(i + 1)
        theta = i * golden_angle
        centroids[cid] = (r * math.cos(theta), r * math.sin(theta))

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

    _clustered_spring_layout(nodes, edges, cluster_fn, cluster_separation=2.2)


# ---------------------------------------------------------------------------
# taxonomical: rooted tree  (UNCHANGED — trees are the right shape here)
# ---------------------------------------------------------------------------

def _layout_taxonomical(nodes: List[Dict], edges: List[Dict]) -> None:
    """Root taxon at top, children spread radially below."""
    G = nx.DiGraph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        G.add_node(n["_id"])
    child_to_parent = {}
    for e in edges:
        if e.get("edge_type") == "is_child_of":
            src = e.get("source_node_id")
            tgt = e.get("target_node_id")
            if src and tgt and src in id_set and tgt in id_set:
                child_to_parent[src] = tgt
                G.add_edge(src, tgt)

    children_set = set(child_to_parent.keys())
    parents_set = set(child_to_parent.values())
    candidates = parents_set - children_set
    root = next(iter(candidates)) if candidates else next(iter(id_set), None)
    if root is None:
        _layout_generic(nodes, edges)
        return

    # Build parent→children map up-front so BFS is O(n) not O(n²)
    children_map: Dict[str, List[str]] = {}
    for child, parent in child_to_parent.items():
        children_map.setdefault(parent, []).append(child)

    levels = {}
    q = deque([(root, 0)])
    visited = {root}
    while q:
        nid, depth = q.popleft()
        levels[nid] = depth
        for child in children_map.get(nid, []):
            if child not in visited:
                visited.add(child)
                q.append((child, depth + 1))

    for nid in id_set:
        if nid not in levels:
            levels[nid] = 0

    LEVEL_HEIGHT = 100
    _leaf_cache: Dict[str, int] = {}

    def count_leaves(nid):
        if nid in _leaf_cache:
            return _leaf_cache[nid]
        children = children_map.get(nid, [])
        result = sum(count_leaves(c) for c in children) if children else 1
        _leaf_cache[nid] = result
        return result

    pos_x: Dict[str, float] = {}

    def assign_x(nid, left_offset):
        w = count_leaves(nid) * 60
        pos_x[nid] = left_offset + w / 2
        cursor = left_offset
        for child in children_map.get(nid, []):
            child_w = count_leaves(child) * 60
            assign_x(child, cursor)
            cursor += child_w

    assign_x(root, 0.0)
    all_x = list(pos_x.values())
    cx = (min(all_x) + max(all_x)) / 2 if all_x else 0

    for n in nodes:
        nid = n["_id"]
        depth = levels.get(nid, 0)
        rx = pos_x.get(nid, 0.0) - cx
        ry = -depth * LEVEL_HEIGHT
        n["x2d"] = round(rx, 1)
        n["y2d"] = round(ry, 1)
        n["x"]   = round(rx, 1)
        n["y"]   = round(ry, 1)
        n["z"]   = round(float(depth) * 50 * ((hash(nid) % 100) / 100 - 0.5), 1)


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

    _clustered_spring_layout(nodes, edges, cluster_fn, cluster_separation=2.0)


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

    _clustered_spring_layout(nodes, edges, cluster_fn, cluster_separation=2.0)


# ---------------------------------------------------------------------------
# physiological_process: cluster by node_type
# ---------------------------------------------------------------------------

def _layout_physiological(nodes: List[Dict], edges: List[Dict]) -> None:
    """Cluster by node_type for physiological-process schema."""

    def cluster_fn(n: Dict) -> str:
        return f"phys:{n.get('node_type', 'other')}"

    _clustered_spring_layout(nodes, edges, cluster_fn, cluster_separation=2.0)


# ---------------------------------------------------------------------------
# chatbot: cluster by node_type
# ---------------------------------------------------------------------------

def _layout_chatbot(nodes: List[Dict], edges: List[Dict]) -> None:
    """Cluster by node_type for chatbot schema."""

    def cluster_fn(n: Dict) -> str:
        return f"chat:{n.get('node_type', 'other')}"

    _clustered_spring_layout(nodes, edges, cluster_fn, cluster_separation=2.5)


# ---------------------------------------------------------------------------
# Dispatch map (populated last so all functions are defined)
# ---------------------------------------------------------------------------

SCHEMA_LAYOUT_MAP["sf_support"]            = _layout_sf_support
SCHEMA_LAYOUT_MAP["taxonomical"]           = _layout_taxonomical
SCHEMA_LAYOUT_MAP["citation"]              = _layout_citation
SCHEMA_LAYOUT_MAP["knowledge_graph"]       = _layout_knowledge_graph
SCHEMA_LAYOUT_MAP["physiological_process"] = _layout_physiological
SCHEMA_LAYOUT_MAP["chatbot"]               = _layout_chatbot
