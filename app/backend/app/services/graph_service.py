"""
Graph service — knowledge graph operations with Cytoscape.js output format.
"""
from typing import Dict, Any, Optional, List

from app.core.database import get_database

# Node colour palette per type
NODE_COLORS: Dict[str, str] = {
    "taxon": "#4ade80",        # green
    "document": "#60a5fa",     # blue
    "concept": "#f97316",      # orange
    "fact": "#a78bfa",         # violet
    "chunk": "#94a3b8",        # slate
    "default": "#e5e7eb",      # light gray
}

NODE_SIZE_BASE = 30
NODE_SIZE_SCALE = 5  # extra pixels per connection degree


class GraphService:
    """Service for knowledge graph operations."""

    def __init__(self):
        self.db = get_database()
        self.nodes_collection = self.db.graph_nodes
        self.edges_collection = self.db.graph_edges

    # ------------------------------------------------------------------
    # Cytoscape.js format
    # ------------------------------------------------------------------

    async def get_cytoscape_graph(
        self,
        graph_type: str = "knowledge",
        depth: int = 2,
        center_node: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return graph data in Cytoscape.js elements format.

        Output shape:
          { "elements": { "nodes": [...], "edges": [...] } }
        """
        filter_query: Dict[str, Any] = {}
        if graph_type != "knowledge":
            filter_query["graph_type"] = graph_type

        nodes: List[Dict[str, Any]] = []
        degree: Dict[str, int] = {}

        async for node in self.nodes_collection.find(filter_query):
            nid = str(node["_id"])
            node_type = node.get("type", "default")
            nodes.append({
                "data": {
                    "id": nid,
                    "label": node.get("label") or node.get("name", nid[:8]),
                    "type": node_type,
                    "color": NODE_COLORS.get(node_type, NODE_COLORS["default"]),
                    "size": NODE_SIZE_BASE,
                    **{k: v for k, v in node.items() if k not in ("_id", "label", "name", "type")},
                }
            })
            degree[nid] = 0

        edges: List[Dict[str, Any]] = []
        async for edge in self.edges_collection.find(filter_query):
            source = str(edge.get("source") or edge.get("_from", ""))
            target = str(edge.get("target") or edge.get("_to", ""))
            edges.append({
                "data": {
                    "id": str(edge["_id"]),
                    "source": source,
                    "target": target,
                    "type": edge.get("type", "related"),
                    "label": edge.get("label", ""),
                    "weight": edge.get("weight", 1.0),
                }
            })
            degree[source] = degree.get(source, 0) + 1
            degree[target] = degree.get(target, 0) + 1

        # Size nodes by degree
        for node in nodes:
            nid = node["data"]["id"]
            node["data"]["size"] = NODE_SIZE_BASE + degree.get(nid, 0) * NODE_SIZE_SCALE

        return {"elements": {"nodes": nodes, "edges": edges}}

    async def expand_node(self, node_id: str, hops: int = 1) -> Dict[str, Any]:
        """
        Return neighboring nodes and edges for a given node (for incremental expansion).
        """
        # Find edges touching node_id
        cursor = self.edges_collection.find(
            {"$or": [{"source": node_id}, {"target": node_id},
                     {"_from": node_id}, {"_to": node_id}]}
        )

        neighbor_ids: set[str] = set()
        new_edges: List[Dict[str, Any]] = []

        async for edge in cursor:
            source = str(edge.get("source") or edge.get("_from", ""))
            target = str(edge.get("target") or edge.get("_to", ""))
            neighbor_ids.add(source)
            neighbor_ids.add(target)
            new_edges.append({
                "data": {
                    "id": str(edge["_id"]),
                    "source": source,
                    "target": target,
                    "type": edge.get("type", "related"),
                    "label": edge.get("label", ""),
                    "weight": edge.get("weight", 1.0),
                }
            })

        neighbor_ids.discard(node_id)

        new_nodes: List[Dict[str, Any]] = []
        for nid in neighbor_ids:
            node = await self.nodes_collection.find_one({"_id": nid})
            if not node:
                continue
            node_type = node.get("type", "default")
            new_nodes.append({
                "data": {
                    "id": str(node["_id"]),
                    "label": node.get("label") or node.get("name", ""),
                    "type": node_type,
                    "color": NODE_COLORS.get(node_type, NODE_COLORS["default"]),
                    "size": NODE_SIZE_BASE,
                }
            })

        return {"elements": {"nodes": new_nodes, "edges": new_edges}}

    # ------------------------------------------------------------------
    # Legacy / query methods
    # ------------------------------------------------------------------

    async def get_graph(self) -> Dict[str, Any]:
        """Raw node/edge lists (kept for backward compatibility)."""
        nodes: List[Dict[str, Any]] = []
        async for node in self.nodes_collection.find():
            node["_id"] = str(node["_id"])
            nodes.append(node)

        edges: List[Dict[str, Any]] = []
        async for edge in self.edges_collection.find():
            edge["_id"] = str(edge["_id"])
            edges.append(edge)

        return {"nodes": nodes, "edges": edges}

    async def query_graph(self, query: str) -> Dict[str, Any]:
        """Text search across node labels."""
        results: List[Dict[str, Any]] = []
        cursor = self.nodes_collection.find(
            {"$or": [
                {"label": {"$regex": query, "$options": "i"}},
                {"name": {"$regex": query, "$options": "i"}},
            ]},
            limit=50,
        )
        async for node in cursor:
            node["_id"] = str(node["_id"])
            results.append(node)

        return {"query": query, "results": results, "count": len(results)}
