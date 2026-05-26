"""
GraphQueryService — live ArangoDB graph queries for visualization.

Replaces the old VisualizationService + GraphBuilderService pair.

Design
------
* No materialization — all graph data is fetched on-demand from ArangoDB
  edge collections and vertex collections via AQL.
* No graph_schemas / graph_nodes / graph_edges MongoDB collections needed.
* Schema definitions are static (BUILTIN_SCHEMAS from models/graph.py).
* Layout computation (NetworkX) happens on-demand, in a thread executor,
  and the results are returned directly to the caller — they are NOT
  persisted (no storage needed; layouts are cheap enough for the data
  sizes we serve).

Module layout
-------------
This file is the slim orchestration class.  The heavier pieces live in
sibling modules:

  graph_query_serialization.py    vertex/edge serializers, schema config,
                                  _aql_limit, _compute_degrees
  graph_query_fetchers.py         per-schema sync ArangoDB fetchers plus the
                                  async chatbot fetcher
  graph_query_layouts.py          schema-specific NetworkX layout functions
                                  and the _apply_layout dispatcher

For backwards compatibility, ``_apply_layout`` and ``_compute_degrees`` are
re-exported from this module so external imports keep working:

    from advandeb_kb.services.graph_query_service import (
        GraphQueryService, _apply_layout, _compute_degrees,
    )

Schema → ArangoDB mapping
--------------------------
  citation              → edge coll: citations          verts: documents
  sf_support            → edge coll: sf_support         verts: documents, facts, stylized_facts
  taxonomical           → edge coll: taxonomical        verts: taxa
  knowledge_graph       → named graph: knowledge_graph  (all verts)
  physiological_process → edge colls: sf_support + knowledge_graph  verts: stylized_facts, taxa
  chatbot               → app MongoDB: chat_sessions/messages + ArangoDB KB

All operations that call self.db (python-arango, synchronous) are wrapped in
run_in_executor so they are safe to call from async FastAPI handlers.

Usage
-----
    from advandeb_kb.services.graph_query_service import GraphQueryService
    svc = GraphQueryService(arango_db, app_mongo_db=app_db)
    schemas = svc.list_schemas()
    data    = await svc.get_graph_data("sf_support", limit=2000)
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from advandeb_kb.database.arango_client import ArangoDatabase
from advandeb_kb.models.graph import BUILTIN_SCHEMAS

# Sibling modules — keep imports here so this stays the single entrypoint.
from advandeb_kb.services.graph_query_fetchers import (
    fetch_chatbot_graph,
    fetch_graph_sync,
)
from advandeb_kb.services.graph_query_layouts import _apply_layout  # noqa: F401 — re-exported
from advandeb_kb.services.graph_query_serialization import (
    _compute_degrees,  # noqa: F401 — re-exported
)

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gqs")


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class GraphQueryService:
    """
    Live ArangoDB graph query service — no materialized collections.

    Args:
        arango_db:   Connected ArangoDatabase instance (synchronous python-arango).
        app_mongo_db: AsyncIOMotorDatabase for the app DB (chat_sessions/messages).
                      Required only for the "chatbot" schema; may be None otherwise.
    """

    def __init__(
        self,
        arango_db: ArangoDatabase,
        app_mongo_db: Any = None,
    ):
        self.db = arango_db
        self.app_db = app_mongo_db  # async Motor db for chat data

    # ------------------------------------------------------------------
    # Schema listing (static — from BUILTIN_SCHEMAS)
    # ------------------------------------------------------------------

    def list_schemas(self) -> List[Dict[str, Any]]:
        """Return all built-in schema definitions as plain dicts."""
        results = []
        for schema in BUILTIN_SCHEMAS:
            results.append({
                "_id": schema["name"],   # use name as stable ID (no MongoDB ObjectId)
                "name": schema["name"],
                "description": schema.get("description", ""),
                "is_builtin": schema.get("is_builtin", True),
                "node_types": schema.get("node_types", []),
                "edge_types": schema.get("edge_types", []),
            })
        return results

    def get_schema_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Return a single schema definition by name."""
        for s in self.list_schemas():
            if s["name"] == name:
                return s
        return None

    # ------------------------------------------------------------------
    # Core graph data fetch (async entry point — uses run_in_executor)
    # ------------------------------------------------------------------

    async def get_graph_data(
        self,
        schema_name: str,
        limit: Optional[int] = 2000,
    ) -> Dict[str, Any]:
        """Return {"nodes": [...], "edges": [...]} for a schema.

        All data is fetched fresh from ArangoDB (no cache).
        """
        if schema_name == "chatbot":
            return await fetch_chatbot_graph(
                self.db, self.app_db, _executor, limit=limit
            )
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _executor,
            fetch_graph_sync,
            self.db,
            schema_name,
            limit,
        )

    async def get_graph_with_layout(
        self,
        schema_name: str,
        layout: str = "force",
        limit: Optional[int] = 2000,
    ) -> Dict[str, Any]:
        """Same as get_graph_data but adds x/y/z/x2d/y2d layout coordinates."""
        data = await self.get_graph_data(schema_name, limit=limit)
        nodes = data["nodes"]
        edges = data["edges"]
        if not nodes:
            return {"nodes": [], "edges": [], "schema": schema_name, "layout": layout}

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            _executor,
            _apply_layout,
            nodes,
            edges,
            schema_name,
        )
        return {"nodes": nodes, "edges": edges, "schema": schema_name, "layout": layout}

    # ------------------------------------------------------------------
    # On-demand loading helpers (async)
    # ------------------------------------------------------------------

    async def get_overview(
        self,
        schema_name: str,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Return top-`limit` nodes by degree, plus internal edges and layout."""
        data = await self.get_graph_data(schema_name, limit=10_000)
        nodes = data["nodes"]
        edges = data["edges"]
        _compute_degrees(nodes, edges)
        nodes_sorted = sorted(nodes, key=lambda n: n.get("degree", 0), reverse=True)[:limit]
        top_ids = {n["_id"] for n in nodes_sorted}
        top_edges = [
            e for e in edges
            if e["source_node_id"] in top_ids and e["target_node_id"] in top_ids
        ]

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            _executor,
            _apply_layout,
            nodes_sorted,
            top_edges,
            schema_name,
        )

        return {"nodes": nodes_sorted, "edges": top_edges}

    async def get_all_edges(self, schema_name: str) -> List[Dict[str, Any]]:
        """Return every edge for the schema."""
        data = await self.get_graph_data(schema_name, limit=50_000)
        return data["edges"]

    async def expand_node(
        self,
        schema_name: str,
        node_id: str,
        loaded_node_ids: List[str],
    ) -> Dict[str, Any]:
        """Return 1-hop neighbors of node_id not already in loaded_node_ids.

        Fetches the full graph then filters in Python — fine for our data sizes.
        """
        data = await self.get_graph_data(schema_name, limit=50_000)
        all_nodes = {n["_id"]: n for n in data["nodes"]}
        all_edges = data["edges"]
        loaded_set = set(loaded_node_ids) | {node_id}

        neighbor_ids: set = set()
        for e in all_edges:
            src, tgt = e["source_node_id"], e["target_node_id"]
            if src == node_id:
                neighbor_ids.add(tgt)
            elif tgt == node_id:
                neighbor_ids.add(src)

        new_ids = neighbor_ids - loaded_set
        new_nodes = [all_nodes[nid] for nid in new_ids if nid in all_nodes]
        all_relevant = new_ids | loaded_set
        new_edges = [
            e for e in all_edges
            if e["source_node_id"] in all_relevant and e["target_node_id"] in all_relevant
            and (e["source_node_id"] in new_ids or e["target_node_id"] in new_ids)
        ]
        return {"nodes": new_nodes, "edges": new_edges}

    async def get_type_nodes(
        self,
        schema_name: str,
        node_type: str,
        loaded_node_ids: List[str],
    ) -> Dict[str, Any]:
        """Return all nodes of node_type not already in loaded_node_ids."""
        data = await self.get_graph_data(schema_name, limit=50_000)
        loaded_set = set(loaded_node_ids)
        new_nodes = [
            n for n in data["nodes"]
            if n["node_type"] == node_type and n["_id"] not in loaded_set
        ]
        new_ids = {n["_id"] for n in new_nodes}
        all_relevant = new_ids | loaded_set
        new_edges = [
            e for e in data["edges"]
            if e["source_node_id"] in all_relevant and e["target_node_id"] in all_relevant
            and (e["source_node_id"] in new_ids or e["target_node_id"] in new_ids)
        ]
        return {"nodes": new_nodes, "edges": new_edges}

    async def get_type_nodes_paged(
        self,
        schema_name: str,
        node_type: str,
        page: int = 0,
        page_size: int = 500,
    ) -> Dict[str, Any]:
        """Return a paginated slice of nodes of node_type."""
        data = await self.get_graph_data(schema_name, limit=50_000)
        type_nodes = [n for n in data["nodes"] if n["node_type"] == node_type]
        total = len(type_nodes)
        start = page * page_size
        sliced = type_nodes[start: start + page_size]
        return {
            "nodes": sliced,
            "edges": [],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": (start + page_size) < total,
        }

    async def get_type_counts(self, schema_name: str) -> Dict[str, Any]:
        """Return {node_type: count} and {edge_type: count} for a schema."""
        data = await self.get_graph_data(schema_name, limit=50_000)
        node_types: Dict[str, int] = {}
        edge_types: Dict[str, int] = {}
        for n in data["nodes"]:
            nt = n.get("node_type", "default")
            node_types[nt] = node_types.get(nt, 0) + 1
        for e in data["edges"]:
            et = e.get("edge_type", "default")
            edge_types[et] = edge_types.get(et, 0) + 1
        return {"node_types": node_types, "edge_types": edge_types}

    async def get_stats(self, schema_name: str) -> Dict[str, Any]:
        """Return node count, edge count, density for a schema."""
        data = await self.get_graph_data(schema_name, limit=50_000)
        nc = len(data["nodes"])
        ec = len(data["edges"])
        density = 0.0
        if nc > 1:
            max_edges = nc * (nc - 1)
            density = ec / max_edges if max_edges else 0.0
        return {"node_count": nc, "edge_count": ec, "density": density}

    # ------------------------------------------------------------------
    # Streaming helper (for SSE endpoint)
    # ------------------------------------------------------------------

    async def iter_graph_stream(
        self,
        schema_name: str,
        limit: int = 5000,
        batch_size: int = 200,
    ):
        """Async generator: yields (event_type, payload_dict) tuples.

        event_type is one of: "nodes", "edges", "done", "error"
        """
        try:
            data = await self.get_graph_data(schema_name, limit=limit)
        except Exception as exc:
            logger.exception("iter_graph_stream schema=%s failed", schema_name)
            yield "error", {"detail": str(exc)}
            return

        nodes = data["nodes"]
        edges = data["edges"]
        emitted_ids: set = set()

        # Stream nodes in batches
        total_batches = max(1, -(-len(nodes) // batch_size))
        batch_idx = 0
        batch: list = []
        for node in nodes:
            emitted_ids.add(node["_id"])
            batch.append(node)
            if len(batch) >= batch_size:
                yield "nodes", {
                    "nodes": batch,
                    "batch": batch_idx,
                    "total_batches": total_batches,
                }
                batch = []
                batch_idx += 1
                await asyncio.sleep(0)

        if batch:
            yield "nodes", {
                "nodes": batch,
                "batch": batch_idx,
                "total_batches": total_batches,
            }
            await asyncio.sleep(0)

        # Stream edges whose both endpoints were emitted
        edge_batch: list = []
        edge_count = 0
        for edge in edges:
            if (edge["source_node_id"] in emitted_ids
                    and edge["target_node_id"] in emitted_ids):
                edge_batch.append(edge)
                edge_count += 1
                if len(edge_batch) >= batch_size * 2:
                    yield "edges", {"edges": edge_batch}
                    edge_batch = []
                    await asyncio.sleep(0)

        if edge_batch:
            yield "edges", {"edges": edge_batch}

        yield "done", {"node_count": len(emitted_ids), "edge_count": edge_count}
