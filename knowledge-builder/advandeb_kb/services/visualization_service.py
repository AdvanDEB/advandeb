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
