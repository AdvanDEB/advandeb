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
from typing import Any, Dict, List

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
# Generic spring layout (fallback)
# ---------------------------------------------------------------------------

def _layout_generic(nodes: List[Dict], edges: List[Dict]) -> None:
    """Generic 2D + 3D confidence-weighted spring layout."""
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

    nc = len(G.nodes)
    if nc == 0:
        return
    k = max(0.3, 2.0 / (nc ** 0.5))
    iterations = max(15, min(50, 2000 // nc))
    scale = 250.0

    try:
        pos2d = nx.spring_layout(G, dim=2, weight="weight", k=k, iterations=iterations, seed=42)
    except Exception:
        pos2d = nx.random_layout(G, dim=2, seed=42)
    try:
        pos3d = nx.spring_layout(G, dim=3, weight="weight", k=k, iterations=iterations, seed=42)
    except Exception:
        pos3d = nx.random_layout(G, dim=3, seed=42)

    for node in nodes:
        nid = node["_id"]
        xy = pos2d.get(nid)
        xyz = pos3d.get(nid)
        node["x2d"] = round(float(xy[0]) * scale, 1) if xy is not None else 0.0
        node["y2d"] = round(float(xy[1]) * scale, 1) if xy is not None else 0.0
        node["x"]   = round(float(xyz[0]) * scale, 1) if xyz is not None else 0.0
        node["y"]   = round(float(xyz[1]) * scale, 1) if xyz is not None else 0.0
        node["z"]   = round(float(xyz[2]) * scale, 1) if xyz is not None else 0.0


# ---------------------------------------------------------------------------
# sf_support: tiered (documents → facts → stylized facts)
# ---------------------------------------------------------------------------

def _layout_sf_support(nodes: List[Dict], edges: List[Dict]) -> None:
    """3-tier horizontal layout: documents (bottom) → facts (middle) → SFs (top)."""
    TIER = {"document": 0, "fact": 1, "stylized_fact": 2}
    TIER_Y_2D = {0: 200.0, 1: 0.0, 2: -200.0}
    TIER_Y_3D = {0: -300.0, 1: 0.0, 2: 300.0}

    G = nx.Graph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        tier = TIER.get(n.get("node_type", ""), 1)
        G.add_node(n["_id"], layer=tier)
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    pos2d = nx.multipartite_layout(G, subset_key="layer", align="horizontal", scale=200)

    _SPRING_CAP = 2000
    tier_subgraphs = {}
    for tier in [0, 1, 2]:
        tier_nodes = [nid for nid, d in G.nodes(data=True) if d.get("layer") == tier]
        if len(tier_nodes) > 1:
            if len(tier_nodes) > _SPRING_CAP:
                sorted_ids = sorted(tier_nodes, key=lambda n: hash(n) & 0xFFFFFF)
                spread = 400.0
                sub_pos = {
                    nid: ((i / (len(sorted_ids) - 1) * 2 - 1) * spread, 0.0)
                    for i, nid in enumerate(sorted_ids)
                }
            else:
                sub = G.subgraph(tier_nodes)
                k_sub = max(0.5, 3.0 / (len(tier_nodes) ** 0.5))
                try:
                    sub_pos = nx.spring_layout(sub, k=k_sub, iterations=30, seed=42)
                except Exception:
                    sub_pos = {n: (0.0, 0.0) for n in tier_nodes}
            tier_subgraphs[tier] = sub_pos
        else:
            tier_subgraphs[tier] = {nid: (0.0, 0.0) for nid in tier_nodes}

    for n in nodes:
        nid = n["_id"]
        tier = TIER.get(n.get("node_type", ""), 1)
        x2d, _ = pos2d.get(nid, (0.0, 0.0))
        n["x2d"] = round(float(x2d), 1)
        n["y2d"] = round(TIER_Y_2D[tier], 1)
        sub_pos = tier_subgraphs.get(tier, {})
        zx, _ = sub_pos.get(nid, (0.0, 0.0))
        n["x"] = round(float(x2d), 1)
        n["y"] = round(TIER_Y_3D[tier], 1)
        n["z"] = round(float(zx) * 150, 1)


# ---------------------------------------------------------------------------
# taxonomical: rooted tree
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

    if not G.nodes:
        return

    try:
        communities = list(nx.community.greedy_modularity_communities(G))
    except Exception:
        communities = [set(G.nodes)]

    node_community: Dict[str, int] = {}
    for i, comm in enumerate(communities):
        for nid in comm:
            node_community[nid] = i

    n_communities = len(communities)
    COMMUNITY_RADIUS = max(250, n_communities * 80)
    INTRA_RADIUS = 80

    centroids: Dict[int, tuple] = {}
    for i in range(n_communities):
        angle = 2 * math.pi * i / n_communities
        centroids[i] = (math.cos(angle) * COMMUNITY_RADIUS, math.sin(angle) * COMMUNITY_RADIUS)

    intra_pos: Dict[str, tuple] = {}
    for i, comm in enumerate(communities):
        if len(comm) < 2:
            for nid in comm:
                intra_pos[nid] = (0.0, 0.0)
            continue
        sub = G.subgraph(comm)
        k_sub = max(0.4, 2.0 / (len(comm) ** 0.5))
        iters = max(20, min(60, 1500 // len(comm)))
        try:
            sub_pos = nx.spring_layout(sub, k=k_sub, iterations=iters, seed=42, scale=INTRA_RADIUS)
        except Exception:
            sub_pos = {nid: (0.0, 0.0) for nid in comm}
        intra_pos.update(sub_pos)

    for n in nodes:
        nid = n["_id"]
        comm_idx = node_community.get(nid, 0)
        cx, cy = centroids.get(comm_idx, (0.0, 0.0))
        lx, ly = intra_pos.get(nid, (0.0, 0.0))
        n["x2d"] = round(cx + lx, 1)
        n["y2d"] = round(cy + ly, 1)
        n["x"]   = round(cx + lx, 1)
        n["y"]   = round(cy + ly, 1)
        n["z"]   = round(float(comm_idx) * 80, 1)


# ---------------------------------------------------------------------------
# knowledge_graph: hub-centered cluster
# ---------------------------------------------------------------------------

def _layout_knowledge_graph(nodes: List[Dict], edges: List[Dict]) -> None:
    """Hub-centered cluster layout.

    High-degree nodes end up near the centre; sparse peripheral nodes orbit
    outward.  Algorithm:
    1. Compute per-node degree.
    2. Group nodes by cluster_id.
    3. Score each cluster by its total internal degree (= its connectivity mass).
    4. Place the heaviest cluster at the origin; spread lighter clusters in
       rings of increasing radius outward so high-degree nodes stay central.
    5. Within each cluster, run a spring sub-layout seeded at (0,0) and scaled
       by cluster mass so dense clusters occupy more screen area.
    """
    if not nodes:
        return

    id_set = {n["_id"] for n in nodes}
    G = nx.Graph()
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set and src != tgt:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    # Build degree map
    degree_map: Dict[str, int] = dict(G.degree())  # type: ignore[arg-type]

    # Group by cluster
    clusters: Dict[str, List[str]] = {}
    for n in nodes:
        cid = (
            n.get("cluster_id")
            or n.get("properties", {}).get("cluster_id")
            or "default"
        )
        clusters.setdefault(cid, []).append(n["_id"])

    node_cluster: Dict[str, str] = {
        nid: cid for cid, nids in clusters.items() for nid in nids
    }

    # Score clusters by total degree mass
    cluster_mass: Dict[str, int] = {
        cid: sum(degree_map.get(nid, 0) for nid in nids)
        for cid, nids in clusters.items()
    }

    # Sort from heaviest (centre) to lightest (outer rings)
    sorted_cids = sorted(clusters.keys(), key=lambda cid: -cluster_mass[cid])
    n_clusters = len(sorted_cids)
    max_mass = max(cluster_mass.values(), default=1) or 1

    # Assign radial positions: cluster 0 at origin, rest spread outward
    BASE_RING_RADIUS = max(600, n_clusters * 120)
    INTRA_RADIUS_BASE = 80

    cluster_centroids: Dict[str, tuple] = {}
    for rank, cid in enumerate(sorted_cids):
        if rank == 0:
            cluster_centroids[cid] = (0.0, 0.0)
        else:
            # Pack clusters into concentric rings of ~6 per ring
            ring = (rank - 1) // 6 + 1
            pos_in_ring = (rank - 1) % 6
            ring_cap = min(6, n_clusters - 1)
            ring_radius = BASE_RING_RADIUS * ring
            theta = 2 * math.pi * pos_in_ring / max(ring_cap, 1)
            cluster_centroids[cid] = (ring_radius * math.cos(theta), ring_radius * math.sin(theta))

    # Intra-cluster spring layout; scale by cluster mass
    intra_pos: Dict[str, tuple] = {}
    _SPRING_CAP = 2000
    for cid, nids in clusters.items():
        mass = cluster_mass.get(cid, 1)
        scale = INTRA_RADIUS_BASE * (1 + 2.0 * (mass / max_mass))
        if len(nids) == 1:
            intra_pos[nids[0]] = (0.0, 0.0)
        elif len(nids) > _SPRING_CAP:
            # Too many nodes — place by degree: high-degree near centre
            sorted_nids = sorted(nids, key=lambda nid: -degree_map.get(nid, 0))
            for i, nid in enumerate(sorted_nids):
                angle = i * 2.399963
                r = scale * math.sqrt(i / len(sorted_nids))
                intra_pos[nid] = (r * math.cos(angle), r * math.sin(angle))
        else:
            sub = G.subgraph(nids)
            k_sub = max(0.5, 3.0 / (len(nids) ** 0.5))
            iters = max(10, min(40, 1000 // len(nids)))
            try:
                sp = nx.spring_layout(sub, k=k_sub, iterations=iters, seed=42, scale=scale)
            except Exception:
                sp = {nid: (0.0, 0.0) for nid in nids}
            intra_pos.update(sp)

    for n in nodes:
        nid = n["_id"]
        cid = node_cluster.get(nid, "default")
        cx, cy = cluster_centroids.get(cid, (0.0, 0.0))
        lx, ly = intra_pos.get(nid, (0.0, 0.0))
        n["x2d"] = round(cx + lx, 1)
        n["y2d"] = round(cy + ly, 1)
        n["x"]   = round(cx + lx, 1)
        n["y"]   = round(cy + ly, 1)
        rank = sorted_cids.index(cid) if cid in sorted_cids else 0
        n["z"] = round(float(rank % 20) * 300 - 3000, 1)


# ---------------------------------------------------------------------------
# physiological_process: confidence-weighted spring
# ---------------------------------------------------------------------------

def _layout_physiological(nodes: List[Dict], edges: List[Dict]) -> None:
    """Confidence-weighted spring layout (2D + 3D)."""
    G = nx.Graph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set and src != tgt:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    nc = len(G.nodes)
    if nc == 0:
        return
    k = max(0.3, 2.0 / (nc ** 0.5))

    try:
        pos2d = nx.spring_layout(G, dim=2, weight="weight", k=k, iterations=60, seed=42)
    except Exception:
        pos2d = nx.random_layout(G, dim=2, seed=42)
    try:
        pos3d = nx.spring_layout(G, dim=3, weight="weight", k=k, iterations=30, seed=7)
    except Exception:
        pos3d = nx.random_layout(G, dim=3, seed=7)

    scale = 250
    for n in nodes:
        nid = n["_id"]
        x2, y2 = pos2d.get(nid, (0.0, 0.0))
        xyz = pos3d.get(nid, (0.0, 0.0, 0.0))
        n["x2d"] = round(float(x2) * scale, 1)
        n["y2d"] = round(float(y2) * scale, 1)
        n["x"]   = round(float(xyz[0]) * scale, 1)
        n["y"]   = round(float(xyz[1]) * scale, 1)
        n["z"]   = round(float(xyz[2]) * scale, 1)


# ---------------------------------------------------------------------------
# chatbot: hub-and-spoke (user → session → docs/facts/SFs/taxa)
# ---------------------------------------------------------------------------

def _layout_chatbot(nodes: List[Dict], edges: List[Dict]) -> None:
    """Hub-and-spoke layout for chatbot schema."""
    TIER = {"user": 0, "chat_session": 1, "document": 2,
            "fact": 3, "stylized_fact": 4, "taxon": 5}
    TIER_RADIUS_2D = {0: 0.0, 1: 200.0, 2: 450.0, 3: 700.0, 4: 900.0, 5: 1100.0}
    TIER_Z = {0: 0.0, 1: 100.0, 2: 200.0, 3: 300.0, 4: 400.0, 5: 500.0}

    id_set = {n["_id"] for n in nodes}

    session_to_user: Dict[str, str] = {}
    for e in edges:
        if e.get("edge_type") == "has_session":
            src = e.get("source_node_id")
            tgt = e.get("target_node_id")
            if src and tgt and src in id_set and tgt in id_set:
                session_to_user[tgt] = src

    user_nodes = [n for n in nodes if n.get("node_type") == "user"]
    user_pos: Dict[str, tuple] = {}
    n_users = len(user_nodes)
    USER_RING = 80.0
    for i, n in enumerate(user_nodes):
        angle = 2 * math.pi * i / max(n_users, 1)
        x = math.cos(angle) * USER_RING
        y = math.sin(angle) * USER_RING
        user_pos[n["_id"]] = (x, y)
        n["x2d"] = round(x, 1);  n["y2d"] = round(y, 1)
        n["x"]   = round(x, 1);  n["y"]   = round(y, 1)
        n["z"]   = round(TIER_Z[0], 1)

    session_nodes = [n for n in nodes if n.get("node_type") == "chat_session"]
    user_sessions: Dict[str, List[str]] = {}
    for sn in session_nodes:
        uid = session_to_user.get(sn["_id"])
        if uid:
            user_sessions.setdefault(uid, []).append(sn["_id"])

    session_pos: Dict[str, tuple] = {}
    for uid, sess_ids in user_sessions.items():
        ux, uy = user_pos.get(uid, (0.0, 0.0))
        n_sess = len(sess_ids)
        for j, sid in enumerate(sess_ids):
            angle = 2 * math.pi * j / max(n_sess, 1)
            session_pos[sid] = (ux + math.cos(angle) * TIER_RADIUS_2D[1],
                                uy + math.sin(angle) * TIER_RADIUS_2D[1])

    orphan_sessions = [sn["_id"] for sn in session_nodes if sn["_id"] not in session_pos]
    for k, sid in enumerate(orphan_sessions):
        angle = 2 * math.pi * k / max(len(orphan_sessions), 1)
        session_pos[sid] = (math.cos(angle) * TIER_RADIUS_2D[1],
                            math.sin(angle) * TIER_RADIUS_2D[1])

    for sn in session_nodes:
        x, y = session_pos.get(sn["_id"], (0.0, 0.0))
        sn["x2d"] = round(x, 1);  sn["y2d"] = round(y, 1)
        sn["x"]   = round(x, 1);  sn["y"]   = round(y, 1)
        sn["z"]   = round(TIER_Z[1], 1)

    G = nx.Graph()
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set and src != tgt:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    for tier_name, tier_idx in [("document", 2), ("fact", 3), ("stylized_fact", 4), ("taxon", 5)]:
        tier_nodes = [n for n in nodes if n.get("node_type") == tier_name]
        if not tier_nodes:
            continue
        radius = TIER_RADIUS_2D[tier_idx]
        z_val = TIER_Z[tier_idx]
        n_tier = len(tier_nodes)
        if n_tier == 1:
            tier_nodes[0].update({"x2d": round(radius, 1), "y2d": 0.0,
                                   "x": round(radius, 1), "y": 0.0, "z": round(z_val, 1)})
            continue
        for idx, n in enumerate(sorted(tier_nodes, key=lambda x: x["_id"])):
            angle = 2 * math.pi * idx / n_tier
            n["x2d"] = round(math.cos(angle) * radius, 1)
            n["y2d"] = round(math.sin(angle) * radius, 1)
            n["x"]   = round(math.cos(angle) * radius, 1)
            n["y"]   = round(math.sin(angle) * radius, 1)
            n["z"]   = round(z_val + (hash(n["_id"]) % 100) * 0.5, 1)


# ---------------------------------------------------------------------------
# Dispatch map (populated last so all functions are defined)
# ---------------------------------------------------------------------------

SCHEMA_LAYOUT_MAP["sf_support"]            = _layout_sf_support
SCHEMA_LAYOUT_MAP["taxonomical"]           = _layout_taxonomical
SCHEMA_LAYOUT_MAP["citation"]              = _layout_citation
SCHEMA_LAYOUT_MAP["knowledge_graph"]       = _layout_knowledge_graph
SCHEMA_LAYOUT_MAP["physiological_process"] = _layout_physiological
SCHEMA_LAYOUT_MAP["chatbot"]               = _layout_chatbot
