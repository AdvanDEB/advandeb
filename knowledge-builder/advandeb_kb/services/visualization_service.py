"""
VisualizationService — serves materialized graph data for the dev-server API.

Reads from graph_schemas, graph_nodes, and graph_edges collections.
Layout computation happens **once** at rebuild time and is persisted to MongoDB;
subsequent reads simply return the stored coordinates without any NetworkX work.
"""
import asyncio
import logging
import math
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

import networkx as nx
from bson import ObjectId

_layout_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nx-layout")

logger = logging.getLogger(__name__)

_LAYOUTS = {
    "force": lambda G: nx.spring_layout(G, k=1, iterations=50, seed=42),
    "spring": lambda G: nx.spring_layout(G, k=1, iterations=50, seed=42),
    "circular": lambda G: nx.circular_layout(G),
    "random": lambda G: nx.random_layout(G, seed=42),
    "shell": lambda G: nx.shell_layout(G),
}


# ---------------------------------------------------------------------------
# Projections — fetch only the fields the frontend actually needs, reducing
# bytes read from MongoDB and Python dict allocations on large graphs.
# ---------------------------------------------------------------------------

NODE_PROJECTION = {
    "_id": 1, "label": 1, "node_type": 1, "entity_collection": 1,
    "cluster_id": 1, "degree": 1, "properties": 1,
    "x": 1, "y": 1, "z": 1, "x2d": 1, "y2d": 1,
}
EDGE_PROJECTION = {
    "_id": 1, "schema_id": 1, "source_node_id": 1, "target_node_id": 1,
    "edge_type": 1, "weight": 1,
}


def _serialize_node(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Slim serializer for graph_node documents — converts known ObjectId fields."""
    out = dict(doc)
    out["_id"] = str(doc["_id"])
    return out


def _serialize_edge(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Slim serializer for graph_edge documents — converts known ObjectId fields."""
    out = dict(doc)
    out["_id"] = str(doc["_id"])
    if "schema_id" in out:
        out["schema_id"] = str(out["schema_id"])
    if "source_node_id" in out:
        out["source_node_id"] = str(out["source_node_id"])
    if "target_node_id" in out:
        out["target_node_id"] = str(out["target_node_id"])
    return out


class VisualizationService:
    def __init__(self, database):
        self.db = database
        self.schemas = database.graph_schemas
        self.nodes = database.graph_nodes
        self.edges = database.graph_edges

    # ------------------------------------------------------------------
    # Schema listing
    # ------------------------------------------------------------------

    async def list_schemas(self) -> List[Dict[str, Any]]:
        """Return all graph_schemas documents as plain dicts (id serialized to str)."""
        results = []
        async for doc in self.schemas.find({}):
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ------------------------------------------------------------------
    # Graph data retrieval
    # ------------------------------------------------------------------

    async def get_graph_data(
        self,
        schema_id: ObjectId,
        limit: int = 300,
    ) -> Dict[str, Any]:
        """Return nodes and edges for a schema, ready for D3/frontend rendering.

        Nodes and edges are returned as plain dicts with ObjectId fields
        serialized to strings.

        Layout is **not** recomputed here — positions stored at build time are
        served directly.  If the first sample of nodes has no stored coordinates
        (legacy data pre-dating this change), a one-off legacy fallback is run.
        """
        node_docs = []
        _nf = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}
        async for doc in self.nodes.find(_nf, NODE_PROJECTION, limit=limit):
            node_docs.append(_serialize_node(doc))

        node_ids = {doc["_id"] for doc in node_docs}

        edge_docs = []
        _ef = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}
        async for doc in self.edges.find(_ef, EDGE_PROJECTION):
            serialized = _serialize_edge(doc)
            # Only include edges where both endpoints are in the node set
            if serialized["source_node_id"] in node_ids and serialized["target_node_id"] in node_ids:
                edge_docs.append(serialized)

        # Task 2a: skip layout computation when stored coordinates exist.
        # Only fall back to legacy on-the-fly computation for data that pre-dates
        # this change (no coordinates stored yet).
        _has_stored = any(
            (n.get("x") or 0) != 0 or (n.get("y") or 0) != 0 or n.get("x2d") is not None
            for n in node_docs[:10]          # sample — avoid scanning all nodes
        )
        if not _has_stored:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                _layout_executor,
                _legacy_confidence_layout,   # legacy fallback only
                node_docs, edge_docs,
            )
        return {"nodes": node_docs, "edges": edge_docs}

    async def get_graph_with_layout(
        self,
        schema_id: ObjectId,
        layout: str = "force",
        limit: int = 300,
    ) -> Dict[str, Any]:
        """Same as get_graph_data but adds x/y positions computed by NetworkX."""
        data = await self.get_graph_data(schema_id, limit=limit)
        nodes = data["nodes"]
        edges = data["edges"]

        if not nodes:
            return {"nodes": [], "edges": [], "layout": layout}

        G = nx.DiGraph()
        for node in nodes:
            G.add_node(node["_id"])
        for edge in edges:
            G.add_edge(edge["source_node_id"], edge["target_node_id"])

        layout_fn = _LAYOUTS.get(layout, _LAYOUTS["force"])
        try:
            pos = layout_fn(G)
        except Exception:
            logger.exception("Layout '%s' failed, falling back to random", layout)
            pos = nx.random_layout(G, seed=42)

        node_positions = {nid: (float(x), float(y)) for nid, (x, y) in pos.items()}
        for node in nodes:
            x, y = node_positions.get(node["_id"], (0.0, 0.0))
            node["x"] = x
            node["y"] = y

        return {"nodes": nodes, "edges": edges, "layout": layout}

    # ------------------------------------------------------------------
    # Task 2b — Persist layout after rebuild
    # ------------------------------------------------------------------

    async def compute_and_store_layout(
        self,
        schema_id: ObjectId,
        schema_name: str,
    ) -> Dict[str, Any]:
        """
        Fetch all nodes + edges for schema_id, compute schema-appropriate 2D and 3D
        layouts, and bulk-write the resulting x/y/z/x2d/y2d coordinates back to
        graph_nodes in MongoDB.

        Returns {"updated": N, "schema": schema_name}.
        """
        from pymongo import UpdateOne

        # 1. Fetch
        node_docs = []
        _nf = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}
        async for doc in self.nodes.find(_nf, NODE_PROJECTION):
            node_docs.append(_serialize_node(doc))

        edge_docs = []
        _ef = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}
        async for doc in self.edges.find(_ef, EDGE_PROJECTION):
            edge_docs.append(_serialize_edge(doc))

        if not node_docs:
            return {"updated": 0, "schema": schema_name}

        # 2. Compute both 2D and 3D layouts in a thread (CPU-bound)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            _layout_executor,
            _dispatch_layout,
            node_docs,
            edge_docs,
            schema_name,
        )

        # 3. Bulk-write back to MongoDB
        ops = []
        for nd in node_docs:
            ops.append(UpdateOne(
                {"_id": ObjectId(nd["_id"])},
                {"$set": {
                    "x":   nd.get("x",   0.0),
                    "y":   nd.get("y",   0.0),
                    "z":   nd.get("z",   0.0),
                    "x2d": nd.get("x2d", nd.get("x", 0.0)),
                    "y2d": nd.get("y2d", nd.get("y", 0.0)),
                }},
            ))

        if ops:
            await self.nodes.bulk_write(ops, ordered=False)

        logger.info(
            "compute_and_store_layout schema=%s name=%s — updated %d nodes",
            schema_id, schema_name, len(ops),
        )
        return {"updated": len(ops), "schema": schema_name}

    # ------------------------------------------------------------------
    # On-demand loading methods
    # ------------------------------------------------------------------

    async def get_all_edges(
        self,
        schema_id: ObjectId,
    ) -> List[Dict[str, Any]]:
        """Return every edge for ``schema_id``.

        Used by the frontend after loading all nodes so that all inter-node
        edges can be rendered in one shot.
        """
        edge_docs = []
        async for doc in self.edges.find(
            {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]},
            EDGE_PROJECTION,
        ):
            edge_docs.append(_serialize_edge(doc))

        logger.info("get_all_edges schema=%s — %d edges", schema_id, len(edge_docs))
        return edge_docs

    async def get_overview(
        self,
        schema_id: ObjectId,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Return the top-`limit` nodes by pre-computed degree plus edges between them.

        Relies on the ``degree`` field written by
        ``GraphBuilderService._post_build_compute_degrees()`` after each build.
        Uses the ``(schema_id, degree)`` compound index for an efficient sorted
        scan instead of the previous O(E) Python-side aggregation loop.

        Returns: { "nodes": [...], "edges": [...] }
        """
        # Fetch top-N nodes by pre-computed degree (uses schema_id + degree index)
        node_docs = []
        _nf = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}
        async for doc in self.nodes.find(
            _nf,
            NODE_PROJECTION,
            sort=[("degree", -1)],
            limit=limit,
        ):
            node_docs.append(_serialize_node(doc))

        if not node_docs:
            return {"nodes": [], "edges": []}

        top_node_id_set = {nd["_id"] for nd in node_docs}
        from bson import ObjectId as _OID
        top_oids = [_OID(nid) for nid in top_node_id_set if _OID.is_valid(nid)]

        # Fetch only edges internal to the top-N set
        edge_docs = []
        async for doc in self.edges.find({
            "$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}],
            "source_node_id": {"$in": top_oids},
            "target_node_id": {"$in": top_oids},
        }, EDGE_PROJECTION):
            edge_docs.append(_serialize_edge(doc))

        logger.info(
            "get_overview schema=%s — %d nodes (limit=%d), %d edges",
            schema_id, len(node_docs), limit, len(edge_docs),
        )
        return {"nodes": node_docs, "edges": edge_docs}

    async def expand_node(
        self,
        schema_id: ObjectId,
        node_id: str,
        loaded_node_ids: List[str],
    ) -> Dict[str, Any]:
        """Return 1-hop neighbors of `node_id` not already in `loaded_node_ids`.

        Also returns:
        - Edges between `node_id` and the newly returned nodes.
        - Edges between newly returned nodes and any node already loaded.

        Returns: { "nodes": [...], "edges": [...] }
        """
        from bson import ObjectId as _OID

        if not _OID.is_valid(node_id):
            return {"nodes": [], "edges": []}

        node_oid = _OID(node_id)
        loaded_set = set(loaded_node_ids)
        loaded_set.add(node_id)  # ensure the pivot itself is treated as loaded

        # Find all direct neighbors (1-hop) via any edge touching node_id
        _ef = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}
        neighbor_ids: set = set()
        async for edge in self.edges.find({
            **_ef,
            "$and": [
                {"$or": [
                    {"source_node_id": node_oid},
                    {"target_node_id": node_oid},
                ]},
            ],
        }, {"source_node_id": 1, "target_node_id": 1}):
            src = str(edge["source_node_id"])
            tgt = str(edge["target_node_id"])
            if src != node_id:
                neighbor_ids.add(src)
            if tgt != node_id:
                neighbor_ids.add(tgt)

        # Keep only NEW neighbors (not already loaded)
        new_neighbor_ids = neighbor_ids - loaded_set
        if not new_neighbor_ids:
            return {"nodes": [], "edges": []}

        # Fetch the new node documents
        new_oids = [_OID(nid) for nid in new_neighbor_ids if _OID.is_valid(nid)]
        node_docs = []
        async for doc in self.nodes.find({"_id": {"$in": new_oids}}, NODE_PROJECTION):
            node_docs.append(_serialize_node(doc))

        # Fetch relevant edges:
        # (a) edges between node_id and new neighbors
        # (b) edges between new neighbors and any loaded node
        all_relevant = new_neighbor_ids | loaded_set
        all_relevant_oids = [_OID(nid) for nid in all_relevant if _OID.is_valid(nid)]

        edge_docs = []
        async for doc in self.edges.find({
            **_ef,
            "source_node_id": {"$in": all_relevant_oids},
            "target_node_id": {"$in": all_relevant_oids},
        }, EDGE_PROJECTION):
            serialized = _serialize_edge(doc)
            src = serialized["source_node_id"]
            tgt = serialized["target_node_id"]
            # Include only edges where at least one endpoint is a newly returned node
            if src in new_neighbor_ids or tgt in new_neighbor_ids:
                edge_docs.append(serialized)

        logger.info(
            "expand_node schema=%s node=%s — %d new nodes, %d edges",
            schema_id, node_id, len(node_docs), len(edge_docs),
        )
        return {"nodes": node_docs, "edges": edge_docs}

    async def get_type_nodes(
        self,
        schema_id: ObjectId,
        node_type: str,
        loaded_node_ids: List[str],
    ) -> Dict[str, Any]:
        """Return all nodes of `node_type` not already in `loaded_node_ids`.

        Also returns edges that connect the newly returned nodes to any node
        already in `loaded_node_ids`.

        Returns: { "nodes": [...], "edges": [...] }
        """
        from bson import ObjectId as _OID

        loaded_set = set(loaded_node_ids)
        _nf = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}
        _ef = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}

        # Fetch all nodes of this type for the schema
        node_docs = []
        async for doc in self.nodes.find({
            **_nf,
            "node_type": node_type,
        }, NODE_PROJECTION):
            serialized = _serialize_node(doc)
            if serialized["_id"] not in loaded_set:
                node_docs.append(serialized)

        if not node_docs:
            return {"nodes": [], "edges": []}

        new_node_id_set = {nd["_id"] for nd in node_docs}
        all_relevant = new_node_id_set | loaded_set
        all_relevant_oids = [_OID(nid) for nid in all_relevant if _OID.is_valid(nid)]

        edge_docs = []
        async for doc in self.edges.find({
            **_ef,
            "source_node_id": {"$in": all_relevant_oids},
            "target_node_id": {"$in": all_relevant_oids},
        }, EDGE_PROJECTION):
            serialized = _serialize_edge(doc)
            src = serialized["source_node_id"]
            tgt = serialized["target_node_id"]
            # Include only edges where at least one endpoint is a newly returned node
            if src in new_node_id_set or tgt in new_node_id_set:
                edge_docs.append(serialized)

        logger.info(
            "get_type_nodes schema=%s type=%s — %d new nodes, %d edges",
            schema_id, node_type, len(node_docs), len(edge_docs),
        )
        return {"nodes": node_docs, "edges": edge_docs}

    async def get_type_nodes_paged(
        self,
        schema_id: ObjectId,
        node_type: str,
        page: int = 0,
        page_size: int = 500,
    ) -> Dict[str, Any]:
        """Return a page of nodes of ``node_type``, with pagination metadata.

        Edges are not included in the response — they should be loaded lazily
        via ``expand_node``.  This avoids the large ``$in`` exclusion list that
        the old ``get_type_nodes`` endpoint required.

        Returns::

            {
                "nodes": [...],
                "edges": [],
                "page": <int>,
                "page_size": <int>,
                "total": <int>,
                "has_more": <bool>,
            }
        """
        skip = page * page_size
        _nf = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}
        node_docs = []
        async for doc in self.nodes.find(
            {**_nf, "node_type": node_type},
            NODE_PROJECTION,
            skip=skip,
            limit=page_size,
        ):
            node_docs.append(_serialize_node(doc))

        total = await self.nodes.count_documents(
            {**_nf, "node_type": node_type}
        )
        return {
            "nodes": node_docs,
            "edges": [],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": (skip + page_size) < total,
        }

    async def get_type_counts(self, schema_id: ObjectId) -> Dict[str, Any]:
        """Return ``{node_type: count}`` and ``{edge_type: count}`` via aggregation.

        Allows the frontend to know which node/edge types exist and their counts
        without loading any node documents.  Useful for filter bars and
        expand-type buttons.
        """
        _schema_filter = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}
        node_pipeline = [
            {"$match": _schema_filter},
            {"$group": {"_id": "$node_type", "count": {"$sum": 1}}},
        ]
        edge_pipeline = [
            {"$match": _schema_filter},
            {"$group": {"_id": "$edge_type", "count": {"$sum": 1}}},
        ]
        node_types: Dict[str, int] = {}
        async for r in self.nodes.aggregate(node_pipeline):
            node_types[r["_id"] or "default"] = r["count"]
        edge_types: Dict[str, int] = {}
        async for r in self.edges.aggregate(edge_pipeline):
            edge_types[r["_id"] or "default"] = r["count"]
        return {"node_types": node_types, "edge_types": edge_types}

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    async def get_stats(self, schema_id: ObjectId) -> Dict[str, Any]:
        """Return basic graph statistics (node count, edge count, density)."""
        _sf = {"$or": [{"schema_id": schema_id}, {"schema_id": str(schema_id)}]}
        node_count = await self.nodes.count_documents(_sf)
        edge_count = await self.edges.count_documents(_sf)

        density = 0.0
        if node_count > 1:
            max_edges = node_count * (node_count - 1)
            density = edge_count / max_edges if max_edges > 0 else 0.0

        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "density": density,
        }


# ---------------------------------------------------------------------------
# Task 4 — Schema-specific layout dispatcher
# ---------------------------------------------------------------------------

# Populated at module bottom once all layout functions are defined.
SCHEMA_LAYOUT_MAP: Dict[str, Any] = {}


def _dispatch_layout(
    nodes: List[Dict],
    edges: List[Dict],
    schema_name: str,
) -> None:
    """Called in a thread executor — blocking NetworkX work.

    Routes to the schema-appropriate layout function.  Falls back to the legacy
    confidence-weighted spring layout for unrecognised schema names.
    """
    fn = SCHEMA_LAYOUT_MAP.get(schema_name, _legacy_confidence_layout)
    fn(nodes, edges)


# ---------------------------------------------------------------------------
# Task 5 — sf_support: 3-tier DAG layout
# ---------------------------------------------------------------------------

def _layout_sf_support(nodes: List[Dict], edges: List[Dict]) -> None:
    """3-tier horizontal layout: documents (bottom), facts (middle), SFs (top)."""
    TIER = {"document": 0, "fact": 1, "stylized_fact": 2}
    # Compact tier spacing — frontend will zoomToFit so absolute scale is less critical,
    # but keep bbox small enough that a 1:1 camera shows most of the graph.
    TIER_Y_2D = {0: 200.0, 1: 0.0, 2: -200.0}   # top→bottom: SFs, facts, docs
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

    # scale=200 keeps x2d in [-200, 200] — fits on a 500px canvas at 1:1
    pos2d = nx.multipartite_layout(G, subset_key="layer", align="horizontal", scale=200)

    # 3D: per-tier layout for z spread within each tier.
    # For tiers with >2000 nodes, spring_layout would take minutes — use a fast
    # deterministic hash-based x-spread instead so this completes in seconds.
    _SPRING_CAP = 2000
    tier_subgraphs = {}
    for tier in [0, 1, 2]:
        tier_nodes = [nid for nid, d in G.nodes(data=True) if d.get("layer") == tier]
        if len(tier_nodes) > 1:
            if len(tier_nodes) > _SPRING_CAP:
                # Fast fallback: spread nodes evenly along x using sorted hash
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

    node_map = {n["_id"]: n for n in nodes}
    for nid, n in node_map.items():
        tier = TIER.get(n.get("node_type", ""), 1)

        x2d, _ = pos2d.get(nid, (0.0, 0.0))
        n["x2d"] = round(float(x2d), 1)
        n["y2d"] = round(TIER_Y_2D[tier], 1)

        sub_pos = tier_subgraphs.get(tier, {})
        zx, _ = sub_pos.get(nid, (0.0, 0.0))
        n["x"]  = round(float(x2d), 1)
        n["y"]  = round(TIER_Y_3D[tier], 1)
        n["z"]  = round(float(zx) * 150, 1)


# ---------------------------------------------------------------------------
# Task 6 — taxonomical: leaf-count-weighted tree layout
# ---------------------------------------------------------------------------

def _layout_taxonomical(nodes: List[Dict], edges: List[Dict]) -> None:
    """Root taxon at top, children spread radially below.  Depth = rank in tree."""
    G = nx.DiGraph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        G.add_node(n["_id"])
    child_to_parent = {}
    for e in edges:
        if e.get("edge_type") == "is_child_of":
            src = e.get("source_node_id")   # child
            tgt = e.get("target_node_id")   # parent
            if src and tgt and src in id_set and tgt in id_set:
                child_to_parent[src] = tgt
                G.add_edge(src, tgt)

    children_set = set(child_to_parent.keys())
    parents_set = set(child_to_parent.values())
    candidates = parents_set - children_set
    root = next(iter(candidates)) if candidates else next(iter(id_set), None)
    if root is None:
        _legacy_confidence_layout(nodes, edges)
        return

    levels = {}
    children_map: Dict[str, List[str]] = {}
    q = deque([(root, 0)])
    visited = {root}
    while q:
        nid, depth = q.popleft()
        levels[nid] = depth
        for src, tgt in child_to_parent.items():
            if tgt == nid and src not in visited:
                visited.add(src)
                children_map.setdefault(nid, []).append(src)
                q.append((src, depth + 1))

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
# Task 7 — citation: community-clustered layout
# ---------------------------------------------------------------------------

def _layout_citation(nodes: List[Dict], edges: List[Dict]) -> None:
    """Papers that cite each other form visible clusters via community detection."""
    G = nx.Graph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set and src != tgt:
            G.add_edge(src, tgt)

    if len(G.nodes) == 0:
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
        centroids[i] = (
            math.cos(angle) * COMMUNITY_RADIUS,
            math.sin(angle) * COMMUNITY_RADIUS,
        )

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
# Task 8 — knowledge_graph: large-scale cluster-seeded layout
# ---------------------------------------------------------------------------

def _layout_knowledge_graph(nodes: List[Dict], edges: List[Dict]) -> None:
    """Up to 15 000 nodes.  Pre-position cluster centroids, then intra-cluster spring."""
    clusters: Dict[str, List[str]] = {}
    for n in nodes:
        cid = (
            n.get("cluster_id")
            or n.get("properties", {}).get("cluster_id")
            or "default"
        )
        clusters.setdefault(cid, []).append(n["_id"])

    n_clusters = len(clusters)
    CLUSTER_RADIUS = max(800, n_clusters * 150)
    INTRA_RADIUS   = min(300, 80 + len(nodes) // 20)

    cluster_centroids: Dict[str, tuple] = {}
    for i, cid in enumerate(sorted(clusters.keys())):
        r = CLUSTER_RADIUS * math.sqrt(i / max(n_clusters, 1))
        theta = i * 2.399963  # golden angle in radians
        cluster_centroids[cid] = (r * math.cos(theta), r * math.sin(theta))

    id_set = {n["_id"] for n in nodes}
    G = nx.Graph()
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set and src != tgt:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    node_cluster: Dict[str, str] = {}
    for cid, nids in clusters.items():
        for nid in nids:
            node_cluster[nid] = cid

    intra_pos: Dict[str, tuple] = {}
    for cid, nids in clusters.items():
        if len(nids) == 1:
            intra_pos[nids[0]] = (0.0, 0.0)
            continue
        sub = G.subgraph(nids)
        k_sub = max(0.5, 3.0 / (len(nids) ** 0.5))
        iters = max(10, min(30, 800 // len(nids)))
        try:
            sp = nx.spring_layout(sub, k=k_sub, iterations=iters, seed=42, scale=INTRA_RADIUS)
        except Exception:
            sp = {nid: (0.0, 0.0) for nid in nids}
        intra_pos.update(sp)

    sorted_cids = sorted(clusters.keys())
    for n in nodes:
        nid = n["_id"]
        cid = node_cluster.get(nid, "default")
        cx, cy = cluster_centroids.get(cid, (0.0, 0.0))
        lx, ly = intra_pos.get(nid, (0.0, 0.0))

        n["x2d"] = round(cx + lx, 1)
        n["y2d"] = round(cy + ly, 1)
        n["x"]   = round(cx + lx, 1)
        n["y"]   = round(cy + ly, 1)
        cluster_idx = sorted_cids.index(cid) if cid in sorted_cids else 0
        n["z"] = round(float(cluster_idx % 20) * 300 - 3000, 1)


# ---------------------------------------------------------------------------
# Task 9 — physiological_process: dual spring layout (2D + 3D)
# ---------------------------------------------------------------------------

def _layout_physiological(nodes: List[Dict], edges: List[Dict]) -> None:
    """Confidence-weighted spring layout with separate 2D and 3D runs."""
    _spring_layout_both(nodes, edges, iterations_2d=60, iterations_3d=30, scale=250)


def _spring_layout_both(
    nodes: List[Dict],
    edges: List[Dict],
    iterations_2d: int,
    iterations_3d: int,
    scale: int,
) -> None:
    """Run spring_layout twice: once dim=2 (→ x2d/y2d), once dim=3 (→ x/y/z)."""
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
        pos2d = nx.spring_layout(G, dim=2, weight="weight", k=k,
                                 iterations=iterations_2d, seed=42)
    except Exception:
        pos2d = nx.random_layout(G, dim=2, seed=42)

    try:
        pos3d = nx.spring_layout(G, dim=3, weight="weight", k=k,
                                 iterations=iterations_3d, seed=7)
    except Exception:
        pos3d = nx.random_layout(G, dim=3, seed=7)

    for n in nodes:
        nid = n["_id"]
        x2, y2 = pos2d.get(nid, (0.0, 0.0))
        xyz = pos3d.get(nid, (0.0, 0.0, 0.0))
        n["x2d"] = round(float(x2)     * scale, 1)
        n["y2d"] = round(float(y2)     * scale, 1)
        n["x"]   = round(float(xyz[0]) * scale, 1)
        n["y"]   = round(float(xyz[1]) * scale, 1)
        n["z"]   = round(float(xyz[2]) * scale, 1)


# ---------------------------------------------------------------------------
# Legacy cleanup — kept as fallback for unrecognised schemas and legacy data
# ---------------------------------------------------------------------------

def _legacy_confidence_layout(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> None:
    """Confidence-weighted spring layout (2D + 3D).

    **Legacy** — only called for:
    - Unrecognised schema names (SCHEMA_LAYOUT_MAP fallback).
    - Data built before this change where stored coordinates are absent.

    Sets x, y, z, x2d, y2d on each node dict in-place.
    """
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

    n = len(G.nodes)
    if n == 0:
        return

    k = max(0.3, 2.0 / (n ** 0.5))
    iterations = max(15, min(50, 2000 // n))

    try:
        pos2d = nx.spring_layout(G, dim=2, weight="weight", k=k, iterations=iterations, seed=42)
    except Exception:
        logger.warning("spring_layout 2D failed, falling back to random layout")
        pos2d = nx.random_layout(G, dim=2, seed=42)

    try:
        pos3d = nx.spring_layout(G, dim=3, weight="weight", k=k, iterations=iterations, seed=42)
    except Exception:
        logger.warning("spring_layout 3D failed, falling back to random layout")
        pos3d = nx.random_layout(G, dim=3, seed=42)

    scale = 250.0
    for node in nodes:
        nid = node["_id"]
        xy = pos2d.get(nid)
        xyz = pos3d.get(nid)
        if xy is not None:
            node["x2d"] = round(float(xy[0]) * scale, 1)
            node["y2d"] = round(float(xy[1]) * scale, 1)
        else:
            node["x2d"] = 0.0
            node["y2d"] = 0.0
        if xyz is not None:
            node["x"] = round(float(xyz[0]) * scale, 1)
            node["y"] = round(float(xyz[1]) * scale, 1)
            node["z"] = round(float(xyz[2]) * scale, 1)
        else:
            node["x"] = 0.0
            node["y"] = 0.0
            node["z"] = 0.0


# ---------------------------------------------------------------------------
# Populate the dispatch map now that all layout functions are defined
# ---------------------------------------------------------------------------

SCHEMA_LAYOUT_MAP["sf_support"]            = _layout_sf_support
SCHEMA_LAYOUT_MAP["taxonomical"]           = _layout_taxonomical
SCHEMA_LAYOUT_MAP["citation"]              = _layout_citation
SCHEMA_LAYOUT_MAP["knowledge_graph"]       = _layout_knowledge_graph
SCHEMA_LAYOUT_MAP["physiological_process"] = _layout_physiological
