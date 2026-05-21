"""Background builder for full graph artifacts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from app.core.config import settings
from advandeb_kb.services.graph_artifact_store import GraphArtifactStore
from advandeb_kb.services.graph_query_service import GraphQueryService, _apply_layout, _compute_degrees


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounds_2d(nodes: List[Dict[str, Any]]) -> Dict[str, float]:
    if not nodes:
        return {"min_x": 0.0, "max_x": 0.0, "min_y": 0.0, "max_y": 0.0}
    xs = [float(node.get("x2d") or 0.0) for node in nodes]
    ys = [float(node.get("y2d") or 0.0) for node in nodes]
    return {
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
    }


def _density(node_count: int, edge_count: int) -> float:
    if node_count <= 1:
        return 0.0
    max_edges = node_count * (node_count - 1)
    return edge_count / max_edges if max_edges else 0.0


def _type_counts(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    node_types: Dict[str, int] = {}
    edge_types: Dict[str, int] = {}
    for node in nodes:
        node_type = node.get("node_type", "unknown")
        node_types[node_type] = node_types.get(node_type, 0) + 1
    for edge in edges:
        edge_type = edge.get("edge_type", "related")
        edge_types[edge_type] = edge_types.get(edge_type, 0) + 1
    return {"node_types": node_types, "edge_types": edge_types}


def _serialize_artifact_node(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(node.get("_id", "")),
        "type": str(node.get("node_type", "unknown")),
        "label": str(node.get("label", "")),
        "entity_collection": str(node.get("entity_collection", "")),
        "entity_id": str(node.get("entity_id", "")),
        "degree": int(node.get("degree") or 0),
        "x2d": float(node.get("x2d") or 0.0),
        "y2d": float(node.get("y2d") or 0.0),
        "cluster_id": node.get("cluster_id"),
        "props": dict(node.get("properties") or {}),
    }


def _serialize_artifact_edge(edge: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(edge.get("_id", "")),
        "type": str(edge.get("edge_type", "related")),
        "source": str(edge.get("source_node_id", "")),
        "target": str(edge.get("target_node_id", "")),
        "weight": float(edge.get("weight") or 1.0),
        "props": dict(edge.get("properties") or {}),
    }


class GraphArtifactBuilder:
    def __init__(self, arango_db: Any, kb_mongo_db: Any, app_mongo_db: Any = None):
        self.query_service = GraphQueryService(arango_db, app_mongo_db=app_mongo_db)
        self.store = GraphArtifactStore(kb_mongo_db, settings.GRAPH_ARTIFACT_DIR)

    async def ensure_indexes(self) -> None:
        await self.store.ensure_indexes()

    async def get_public_meta(self, schema_id: str, schema_name: str | None = None) -> Dict[str, Any]:
        return await self.store.get_public_meta(schema_id, schema_name)

    async def list_public_meta_map(self) -> Dict[str, Dict[str, Any]]:
        return await self.store.list_public_meta_map()

    async def build_schema_artifact(self, schema_id: str) -> Dict[str, Any]:
        await self.ensure_indexes()
        schema = self.query_service.get_schema_by_name(schema_id)
        if not schema:
            raise ValueError(f"Unknown graph schema: {schema_id}")

        build_id = uuid4().hex
        source_revision = _now_iso()
        await self.store.mark_status(
            schema_id,
            schema["name"],
            "building",
            build_id=build_id,
            source_revision=source_revision,
        )

        try:
            payload, meta = await self._build_artifact_payload(schema_id, schema["name"], build_id, source_revision)
            written = await self.store.write_artifact_payload(schema_id, build_id, payload)
            meta.update(written)
            await self.store.publish_artifact(schema_id, schema["name"], meta)
            return await self.store.get_public_meta(schema_id, schema["name"])
        except Exception as exc:
            await self.store.mark_status(
                schema_id,
                schema["name"],
                "failed",
                build_id=build_id,
                source_revision=source_revision,
                error=str(exc),
            )
            raise

    async def _build_artifact_payload(
        self,
        schema_id: str,
        schema_name: str,
        build_id: str,
        source_revision: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        data = await self.query_service.get_graph_data(schema_id, limit=None)
        nodes = list(data.get("nodes") or [])
        edges = list(data.get("edges") or [])

        _compute_degrees(nodes, edges)
        if nodes:
            await asyncio.to_thread(_apply_layout, nodes, edges, schema_id)

        built_at = _now_iso()
        type_counts = _type_counts(nodes, edges)
        node_count = len(nodes)
        edge_count = len(edges)
        bounds_2d = _bounds_2d(nodes)
        payload = {
            "format": "advandeb-graph-artifact",
            "format_version": 1,
            "schema_id": schema_id,
            "schema_name": schema_name,
            "build_id": build_id,
            "built_at": built_at,
            "source_revision": source_revision,
            "layout_name": settings.GRAPH_ARTIFACT_LAYOUT_NAME,
            "stats": {
                "node_count": node_count,
                "edge_count": edge_count,
                "density": _density(node_count, edge_count),
                "bounds_2d": bounds_2d,
            },
            "type_counts": type_counts,
            "nodes": [_serialize_artifact_node(node) for node in nodes],
            "edges": [_serialize_artifact_edge(edge) for edge in edges],
        }
        meta = {
            "build_id": build_id,
            "source_revision": source_revision,
            "built_at": built_at,
            "layout_name": settings.GRAPH_ARTIFACT_LAYOUT_NAME,
            "node_count": node_count,
            "edge_count": edge_count,
            "density": payload["stats"]["density"],
            "type_counts": type_counts,
            "bounds_2d": bounds_2d,
        }
        return payload, meta
