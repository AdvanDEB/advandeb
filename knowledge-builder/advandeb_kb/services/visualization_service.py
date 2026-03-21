"""
VisualizationService — serves materialized graph data for the dev-server API.

Reads from graph_schemas, graph_nodes, and graph_edges collections.
Optionally computes x/y layout positions via NetworkX.
"""
import logging
from typing import Any, Dict, List, Optional

import networkx as nx
from bson import ObjectId

logger = logging.getLogger(__name__)

_LAYOUTS = {
    "force": lambda G: nx.spring_layout(G, k=1, iterations=50, seed=42),
    "spring": lambda G: nx.spring_layout(G, k=1, iterations=50, seed=42),
    "circular": lambda G: nx.circular_layout(G),
    "random": lambda G: nx.random_layout(G, seed=42),
    "shell": lambda G: nx.shell_layout(G),
}


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
        """
        node_docs = []
        async for doc in self.nodes.find({"schema_id": schema_id}, limit=limit):
            node_docs.append(_serialize(doc))

        node_ids = {doc["_id"] for doc in node_docs}

        edge_docs = []
        async for doc in self.edges.find({"schema_id": schema_id}):
            serialized = _serialize(doc)
            # Only include edges where both endpoints are in the node set
            if serialized["source_node_id"] in node_ids and serialized["target_node_id"] in node_ids:
                edge_docs.append(serialized)

        _apply_confidence_layout(node_docs, edge_docs)
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
    # On-demand loading methods
    # ------------------------------------------------------------------

    async def get_overview(
        self,
        schema_id: ObjectId,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Return the top-`limit` nodes by degree plus edges between them.

        Degree is computed as the total number of edges (as source or target)
        touching each node.  Hub nodes dominate — for sf_support graphs expect
        stylized_facts to appear at the top.

        Returns: { "nodes": [...], "edges": [...] }
        """
        # Aggregate degree map: count how many edges touch each node
        degree_map: Dict[str, int] = {}

        async for edge in self.edges.find(
            {"schema_id": schema_id},
            {"source_node_id": 1, "target_node_id": 1},
        ):
            src = str(edge["source_node_id"])
            tgt = str(edge["target_node_id"])
            degree_map[src] = degree_map.get(src, 0) + 1
            degree_map[tgt] = degree_map.get(tgt, 0) + 1

        # Top-N node IDs by degree
        top_node_ids_str = [
            nid for nid, _ in sorted(degree_map.items(), key=lambda x: -x[1])[:limit]
        ]

        # Also include nodes with zero degree if we haven't reached the limit yet
        if len(top_node_ids_str) < limit:
            async for node in self.nodes.find(
                {"schema_id": schema_id},
                {"_id": 1},
                limit=limit - len(top_node_ids_str),
            ):
                nid_str = str(node["_id"])
                if nid_str not in set(top_node_ids_str):
                    top_node_ids_str.append(nid_str)

        top_node_id_set = set(top_node_ids_str)

        # Fetch the actual node documents for the top-N IDs
        from bson import ObjectId as _OID
        top_oids = [_OID(nid) for nid in top_node_ids_str if _OID.is_valid(nid)]
        node_docs = []
        async for doc in self.nodes.find({"_id": {"$in": top_oids}}):
            serialized = _serialize(doc)
            serialized["degree"] = degree_map.get(serialized["_id"], 0)
            node_docs.append(serialized)

        # Fetch edges where both source and target are in the top-N set
        edge_docs = []
        async for doc in self.edges.find({"schema_id": schema_id}):
            serialized = _serialize(doc)
            if (
                serialized["source_node_id"] in top_node_id_set
                and serialized["target_node_id"] in top_node_id_set
            ):
                edge_docs.append(serialized)

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
        neighbor_ids: set = set()
        async for edge in self.edges.find({
            "schema_id": schema_id,
            "$or": [
                {"source_node_id": node_oid},
                {"target_node_id": node_oid},
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
        async for doc in self.nodes.find({"_id": {"$in": new_oids}}):
            node_docs.append(_serialize(doc))

        # Fetch relevant edges:
        # (a) edges between node_id and new neighbors
        # (b) edges between new neighbors and any loaded node
        all_relevant = new_neighbor_ids | loaded_set
        all_relevant_oids = [_OID(nid) for nid in all_relevant if _OID.is_valid(nid)]

        edge_docs = []
        async for doc in self.edges.find({
            "schema_id": schema_id,
            "source_node_id": {"$in": all_relevant_oids},
            "target_node_id": {"$in": all_relevant_oids},
        }):
            serialized = _serialize(doc)
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

        # Fetch all nodes of this type for the schema
        node_docs = []
        async for doc in self.nodes.find({
            "schema_id": schema_id,
            "node_type": node_type,
        }):
            serialized = _serialize(doc)
            if serialized["_id"] not in loaded_set:
                node_docs.append(serialized)

        if not node_docs:
            return {"nodes": [], "edges": []}

        new_node_id_set = {nd["_id"] for nd in node_docs}
        all_relevant = new_node_id_set | loaded_set
        all_relevant_oids = [_OID(nid) for nid in all_relevant if _OID.is_valid(nid)]

        edge_docs = []
        async for doc in self.edges.find({
            "schema_id": schema_id,
            "source_node_id": {"$in": all_relevant_oids},
            "target_node_id": {"$in": all_relevant_oids},
        }):
            serialized = _serialize(doc)
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

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    async def get_stats(self, schema_id: ObjectId) -> Dict[str, Any]:
        """Return basic graph statistics (node count, edge count, density)."""
        node_count = await self.nodes.count_documents({"schema_id": schema_id})
        edge_count = await self.edges.count_documents({"schema_id": schema_id})

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
# Helpers
# ---------------------------------------------------------------------------

def _apply_confidence_layout(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
    """Compute confidence-weighted spring layout and set x, y on each node dict in-place.

    Higher edge weight (confidence) → stronger spring → nodes end up closer.
    Lower edge weight → weaker spring → nodes drift further apart.
    This makes the spatial distance between nodes a direct proxy for epistemic
    distance: well-supported nodes cluster tightly around their stylized facts;
    uncertain or tenuous connections radiate outward.

    Iterations are adaptive: more iterations for small graphs (better layout),
    fewer for large graphs (acceptable layout in reasonable time).
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

    # k: ideal inter-node distance; scale down for large graphs
    k = max(0.3, 2.0 / (n ** 0.5))
    # Adaptive iterations: small graph → more iterations (better layout)
    iterations = max(15, min(100, 5000 // n))

    try:
        # weight='weight': nx spring_layout multiplies spring force by weight,
        # so higher weight = stronger attraction = closer nodes in final layout.
        pos = nx.spring_layout(G, weight="weight", k=k, iterations=iterations, seed=42)
    except Exception:
        logger.warning("spring_layout failed, falling back to random layout")
        pos = nx.random_layout(G, seed=42)

    scale = 600.0
    for node in nodes:
        xy = pos.get(node["_id"])
        if xy is not None:
            node["x"] = round(float(xy[0]) * scale, 1)
            node["y"] = round(float(xy[1]) * scale, 1)
        else:
            node["x"] = 0.0
            node["y"] = 0.0


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively convert ObjectId values to strings for JSON serialization."""
    out = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, dict):
            out[k] = _serialize(v)
        elif isinstance(v, list):
            out[k] = [str(i) if isinstance(i, ObjectId) else i for i in v]
        else:
            out[k] = v
    return out
