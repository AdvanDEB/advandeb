"""Materialized graph snapshots for stable visualization views.

Snapshots are stored in MongoDB and currently expose two coherent views:

1. Root cluster graph: one node per cluster, aggregated inter-cluster edges.
2. Expanded cluster graph: one selected cluster expanded in place while the
   surrounding cluster context remains visible.

This gives the frontend a stable, fully connected scene without visibly
streaming nodes onto the canvas.
"""

from __future__ import annotations

import asyncio
import copy
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from advandeb_kb.services.graph_query_service import GraphQueryService
from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue


_snapshot_locks: dict[str, asyncio.Lock] = {}
MAX_CLUSTER_VIEW_NODES = 180
SNAPSHOT_FORMAT_VERSION = 1


def _get_snapshot_lock(schema_name: str) -> asyncio.Lock:
    lock = _snapshot_locks.get(schema_name)
    if lock is None:
        lock = asyncio.Lock()
        _snapshot_locks[schema_name] = lock
    return lock


def _cluster_node_id(schema_name: str, cluster_id: str) -> str:
    return f"cluster::{schema_name}::{cluster_id}"


def _stable_seed(text: str) -> int:
    return sum((index + 1) * ord(ch) for index, ch in enumerate(text))


def _cluster_label(cluster_id: str, node_types: Dict[str, int]) -> str:
    bucket_label = ""
    base_cluster_id = cluster_id
    if "::bucket:" in cluster_id:
        base_cluster_id, _, suffix = cluster_id.partition("::bucket:")
        bucket_index, _, bucket_total = suffix.partition(":")
        if bucket_index and bucket_total:
            bucket_label = f" [{bucket_index}/{bucket_total}]"

    prefix, _, suffix = base_cluster_id.partition(":")
    dominant_type = max(node_types.items(), key=lambda item: item[1])[0] if node_types else prefix or "cluster"
    if not suffix:
        return base_cluster_id.replace("_", " ") + bucket_label
    return f"{suffix.replace('_', ' ')} {dominant_type.replace('_', ' ')}{bucket_label}"


def _dominant_key(counts: Dict[str, int], fallback: str) -> str:
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0] if counts else fallback


def _stable_spiral_positions(items: Iterable[str], spacing: float, start_radius: float) -> Dict[str, tuple[float, float]]:
    positions: Dict[str, tuple[float, float]] = {}
    for index, item in enumerate(sorted(items)):
        angle = index * 2.399963229728653
        radius = start_radius + spacing * math.sqrt(index + 1)
        positions[item] = (math.cos(angle) * radius, math.sin(angle) * radius)
    return positions


def _layout_cluster_members(nodes: List[Dict[str, Any]], center: tuple[float, float]) -> None:
    if not nodes:
        return

    cx, cy = center
    by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for node in sorted(nodes, key=lambda item: (item.get("node_type", ""), item.get("label", ""), item.get("_id", ""))):
        by_type[node.get("node_type", "unknown")].append(node)

    type_rings = {node_type: 110.0 + idx * 90.0 for idx, node_type in enumerate(sorted(by_type))}
    z_layers = {node_type: idx * 120.0 for idx, node_type in enumerate(sorted(by_type))}

    for node_type, members in by_type.items():
        count = len(members)
        radius = type_rings[node_type]
        z_base = z_layers[node_type]
        for index, node in enumerate(members):
            if count == 1:
                dx = dy = 0.0
            else:
                angle = (2 * math.pi * index / count) + (_stable_seed(node_type) % 360) * math.pi / 180.0
                dx = math.cos(angle) * radius
                dy = math.sin(angle) * radius
            node["x2d"] = round(cx + dx, 1)
            node["y2d"] = round(cy + dy, 1)
            node["x"] = round(cx + dx, 1)
            node["y"] = round(cy + dy, 1)
            node["z"] = round(z_base + ((index % 7) - 3) * 18.0, 1)


def _snapshot_density(node_count: int, edge_count: int) -> float:
    if node_count <= 1:
        return 0.0
    max_edges = node_count * (node_count - 1)
    return edge_count / max_edges if max_edges else 0.0


def _normalize_node(node: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
    normalized = copy.deepcopy(node)
    normalized.setdefault("schema_id", schema_name)
    normalized.setdefault("properties", {})
    return normalized


def _normalize_edge(edge: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
    normalized = copy.deepcopy(edge)
    normalized.setdefault("schema_id", schema_name)
    normalized.setdefault("properties", {})
    return normalized


def _snapshot_doc_is_valid(doc: Optional[Dict[str, Any]]) -> bool:
    if not doc:
        return False
    if doc.get("format_version") != SNAPSHOT_FORMAT_VERSION:
        return False
    if not isinstance(doc.get("root_nodes"), list):
        return False
    if not isinstance(doc.get("root_edges"), list):
        return False
    if not isinstance(doc.get("type_counts"), dict):
        return False
    if not isinstance(doc.get("stats"), dict):
        return False
    stats = doc.get("stats") or {}
    node_count = int(stats.get("node_count") or stats.get("nodes") or 0)
    if node_count > 0 and len(doc.get("root_nodes") or []) == 0:
        return False
    for node in doc.get("root_nodes") or []:
        if not isinstance(node, dict):
            return False
        if not isinstance(node.get("properties") or {}, dict):
            return False
    for edge in doc.get("root_edges") or []:
        if not isinstance(edge, dict):
            return False
        if not isinstance(edge.get("properties") or {}, dict):
            return False
    return True


class GraphSnapshotService:
    META_COLLECTION = "graph_snapshot_meta"
    CLUSTER_COLLECTION = "graph_snapshot_cluster_views"

    def __init__(self, arango_db: Any, kb_mongo_db: Any, app_mongo_db: Any = None):
        self.kb_db = kb_mongo_db
        self.query_service = GraphQueryService(arango_db, app_mongo_db=app_mongo_db)

    async def ensure_indexes(self) -> None:
        await self.kb_db[self.META_COLLECTION].create_index("schema_id", unique=True, name="graph_snapshot_meta_schema")
        await self.kb_db[self.CLUSTER_COLLECTION].create_index(
            [("schema_id", 1), ("version", 1), ("cluster_id", 1)],
            unique=True,
            name="graph_snapshot_cluster_schema_version_cluster",
        )

    async def get_view(
        self,
        schema_name: str,
        expanded_cluster_id: Optional[str] = None,
        force_rebuild: bool = False,
    ) -> Dict[str, Any]:
        snapshot = await self.ensure_snapshot(schema_name, force_rebuild=force_rebuild)
        if not expanded_cluster_id:
            return self._root_response(snapshot)

        cluster_doc = await self.kb_db[self.CLUSTER_COLLECTION].find_one({
            "schema_id": schema_name,
            "version": snapshot["version"],
            "cluster_id": expanded_cluster_id,
        })
        if not cluster_doc:
            return self._root_response(snapshot)

        expanded_node_id = _cluster_node_id(schema_name, expanded_cluster_id)
        nodes = [
            _normalize_node(node, schema_name)
            for node in snapshot["root_nodes"]
            if node["_id"] != expanded_node_id
        ]
        nodes.extend(_normalize_node(node, schema_name) for node in cluster_doc.get("nodes", []))

        edges = [
            _normalize_edge(edge, schema_name)
            for edge in snapshot["root_edges"]
            if edge["source_node_id"] != expanded_node_id and edge["target_node_id"] != expanded_node_id
        ]
        edges.extend(_normalize_edge(edge, schema_name) for edge in cluster_doc.get("internal_edges", []))
        edges.extend(_normalize_edge(edge, schema_name) for edge in cluster_doc.get("external_edges", []))

        return {
            "schema": schema_name,
            "mode": "expanded_cluster",
            "expanded_cluster_id": expanded_cluster_id,
            "snapshot_version": snapshot["version"],
            "built_at": snapshot.get("built_at"),
            "nodes": nodes,
            "edges": edges,
            "stats": snapshot["stats"],
            "type_counts": snapshot["type_counts"],
        }

    async def get_stats(self, schema_name: str) -> Dict[str, Any]:
        snapshot = await self.ensure_snapshot(schema_name)
        return snapshot["stats"]

    async def get_type_counts(self, schema_name: str) -> Dict[str, Any]:
        snapshot = await self.ensure_snapshot(schema_name)
        return snapshot["type_counts"]

    async def rebuild_snapshot(self, schema_name: str) -> Dict[str, Any]:
        return await self.ensure_snapshot(schema_name, force_rebuild=True)

    async def ensure_snapshot(self, schema_name: str, force_rebuild: bool = False) -> Dict[str, Any]:
        await self.ensure_indexes()
        lock = _get_snapshot_lock(schema_name)
        async with lock:
            existing = await self.kb_db[self.META_COLLECTION].find_one({"_id": schema_name})
            if existing and not _snapshot_doc_is_valid(existing):
                force_rebuild = True
            if existing and not force_rebuild and not graph_rebuild_queue.is_dirty(schema_name):
                return existing

            built = await self._build_snapshot(schema_name, previous=existing)
            graph_rebuild_queue.clear_dirty(schema_name)
            return built

    async def _build_snapshot(self, schema_name: str, previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = await self.query_service.get_graph_data(schema_name, limit=None)
        nodes = data["nodes"]
        edges = data["edges"]

        node_types: Dict[str, int] = defaultdict(int)
        edge_types: Dict[str, int] = defaultdict(int)
        base_clusters: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        cluster_node_types: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        node_to_cluster: Dict[str, str] = {}

        for node in nodes:
            node_type = node.get("node_type", "unknown")
            base_cluster_id = (
                node.get("cluster_id")
                or node.get("properties", {}).get("cluster_id")
                or node_type
            )
            node_types[node_type] += 1
            base_clusters[base_cluster_id].append(node)

        clusters: Dict[str, List[Dict[str, Any]]] = {}
        cluster_base_ids: Dict[str, str] = {}
        for base_cluster_id, members in base_clusters.items():
            ordered_members = sorted(
                members,
                key=lambda item: (item.get("node_type", ""), item.get("label", ""), item.get("_id", "")),
            )
            bucket_total = max(1, math.ceil(len(ordered_members) / MAX_CLUSTER_VIEW_NODES))
            for bucket_index in range(bucket_total):
                cluster_id = (
                    base_cluster_id
                    if bucket_total == 1
                    else f"{base_cluster_id}::bucket:{bucket_index + 1}:{bucket_total}"
                )
                chunk = ordered_members[
                    bucket_index * MAX_CLUSTER_VIEW_NODES:(bucket_index + 1) * MAX_CLUSTER_VIEW_NODES
                ]
                clusters[cluster_id] = chunk
                cluster_base_ids[cluster_id] = base_cluster_id
                for node in chunk:
                    node_to_cluster[node["_id"]] = cluster_id
                    cluster_node_types[cluster_id][node.get("node_type", "unknown")] += 1

        cluster_positions = _stable_spiral_positions(clusters.keys(), spacing=170.0, start_radius=260.0)
        root_edge_acc: Dict[tuple[str, str], Dict[str, Any]] = {}
        internal_edges: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        internal_edge_counts: Dict[str, int] = defaultdict(int)
        external_node_links: Dict[str, Dict[tuple[str, str], Dict[str, Any]]] = defaultdict(dict)

        for edge in edges:
            edge_type = edge.get("edge_type", "related")
            edge_types[edge_type] += 1
            src = edge.get("source_node_id")
            tgt = edge.get("target_node_id")
            src_cluster = node_to_cluster.get(src)
            tgt_cluster = node_to_cluster.get(tgt)
            if not src_cluster or not tgt_cluster:
                continue
            if src_cluster == tgt_cluster:
                internal_edges[src_cluster].append(_normalize_edge(edge, schema_name))
                internal_edge_counts[src_cluster] += 1
                continue

            a, b = sorted((src_cluster, tgt_cluster))
            pair_key = (a, b)
            pair = root_edge_acc.get(pair_key)
            if pair is None:
                pair = {
                    "_id": f"cluster-edge::{schema_name}::{a}::{b}",
                    "source_node_id": _cluster_node_id(schema_name, a),
                    "target_node_id": _cluster_node_id(schema_name, b),
                    "edge_type": edge_type,
                    "weight": 0.0,
                    "properties": {
                        "snapshot_kind": "cluster_edge",
                        "cluster_pair": [a, b],
                        "edge_types": {},
                    },
                }
                root_edge_acc[pair_key] = pair
            pair["weight"] += float(edge.get("weight") or 1.0)
            pair["properties"]["edge_types"][edge_type] = pair["properties"]["edge_types"].get(edge_type, 0) + 1
            pair["edge_type"] = _dominant_key(pair["properties"]["edge_types"], edge_type)

            link_key = (src, tgt_cluster)
            link = external_node_links[src_cluster].get(link_key)
            if link is None:
                link = {
                    "_id": f"cluster-link::{schema_name}::{src}::{tgt_cluster}",
                    "source_node_id": src,
                    "target_node_id": _cluster_node_id(schema_name, tgt_cluster),
                    "edge_type": edge_type,
                    "weight": 0.0,
                    "properties": {
                        "snapshot_kind": "node_to_cluster_edge",
                        "other_cluster_id": tgt_cluster,
                        "edge_types": {},
                    },
                }
                external_node_links[src_cluster][link_key] = link
            link["weight"] += float(edge.get("weight") or 1.0)
            link["properties"]["edge_types"][edge_type] = link["properties"]["edge_types"].get(edge_type, 0) + 1
            link["edge_type"] = _dominant_key(link["properties"]["edge_types"], edge_type)

            reverse_key = (tgt, src_cluster)
            reverse = external_node_links[tgt_cluster].get(reverse_key)
            if reverse is None:
                reverse = {
                    "_id": f"cluster-link::{schema_name}::{tgt}::{src_cluster}",
                    "source_node_id": tgt,
                    "target_node_id": _cluster_node_id(schema_name, src_cluster),
                    "edge_type": edge_type,
                    "weight": 0.0,
                    "properties": {
                        "snapshot_kind": "node_to_cluster_edge",
                        "other_cluster_id": src_cluster,
                        "edge_types": {},
                    },
                }
                external_node_links[tgt_cluster][reverse_key] = reverse
            reverse["weight"] += float(edge.get("weight") or 1.0)
            reverse["properties"]["edge_types"][edge_type] = reverse["properties"]["edge_types"].get(edge_type, 0) + 1
            reverse["edge_type"] = _dominant_key(reverse["properties"]["edge_types"], edge_type)

        root_nodes: List[Dict[str, Any]] = []
        cluster_docs: List[Dict[str, Any]] = []
        built_at = datetime.now(timezone.utc)
        version = int(previous.get("version", 0)) + 1 if previous else 1

        root_edge_counts: Dict[str, int] = defaultdict(int)
        for edge in root_edge_acc.values():
            root_edge_counts[edge["source_node_id"]] += 1
            root_edge_counts[edge["target_node_id"]] += 1

        for cluster_id in sorted(clusters):
            cluster_nodes = [_normalize_node(node, schema_name) for node in clusters[cluster_id]]
            center = cluster_positions[cluster_id]
            member_nodes: List[Dict[str, Any]] = []
            for node in cluster_nodes:
                props = dict(node.get("properties") or {})
                props["snapshot_kind"] = "cluster_member"
                props["snapshot_cluster_id"] = cluster_id
                props["snapshot_base_cluster_id"] = cluster_base_ids[cluster_id]
                node["properties"] = props
                member_nodes.append(node)
            _layout_cluster_members(member_nodes, center)

            cluster_label = _cluster_label(cluster_id, dict(cluster_node_types[cluster_id]))
            cluster_node_id = _cluster_node_id(schema_name, cluster_id)
            cx, cy = center
            root_nodes.append({
                "_id": cluster_node_id,
                "schema_id": schema_name,
                "label": cluster_label,
                "node_type": "cluster",
                "entity_collection": "graph_snapshot_cluster",
                "entity_id": cluster_id,
                "degree": root_edge_counts.get(cluster_node_id, 0),
                "properties": {
                    "snapshot_kind": "cluster",
                    "snapshot_cluster_id": cluster_id,
                    "snapshot_base_cluster_id": cluster_base_ids[cluster_id],
                    "child_node_count": len(member_nodes),
                    "child_edge_count": internal_edge_counts.get(cluster_id, 0),
                    "child_node_types": dict(cluster_node_types[cluster_id]),
                    "dominant_node_type": _dominant_key(dict(cluster_node_types[cluster_id]), "cluster"),
                },
                "x2d": round(cx, 1),
                "y2d": round(cy, 1),
                "x": round(cx, 1),
                "y": round(cy, 1),
                "z": round(float(_stable_seed(cluster_id) % 400) - 200.0, 1),
            })

            cluster_docs.append({
                "schema_id": schema_name,
                "version": version,
                "format_version": SNAPSHOT_FORMAT_VERSION,
                "cluster_id": cluster_id,
                "label": cluster_label,
                "node_count": len(member_nodes),
                "built_at": built_at,
                "nodes": member_nodes,
                "internal_edges": [_normalize_edge(edge, schema_name) for edge in internal_edges.get(cluster_id, [])],
                "external_edges": [_normalize_edge(edge, schema_name) for edge in external_node_links.get(cluster_id, {}).values()],
            })

        meta_doc = {
            "_id": schema_name,
            "schema_id": schema_name,
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "version": version,
            "status": "ready",
            "built_at": built_at,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "nodes": len(nodes),
                "edges": len(edges),
                "density": _snapshot_density(len(nodes), len(edges)),
                "cluster_count": len(clusters),
            },
            "type_counts": {
                "node_types": dict(node_types),
                "edge_types": dict(edge_types),
            },
            "root_nodes": [_normalize_node(node, schema_name) for node in root_nodes],
            "root_edges": [_normalize_edge(edge, schema_name) for edge in root_edge_acc.values()],
        }

        await self.kb_db[self.META_COLLECTION].replace_one({"_id": schema_name}, meta_doc, upsert=True)
        await self.kb_db[self.CLUSTER_COLLECTION].delete_many({"schema_id": schema_name})
        if cluster_docs:
            await self.kb_db[self.CLUSTER_COLLECTION].insert_many(cluster_docs)
        return meta_doc

    def _root_response(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "schema": snapshot["schema_id"],
            "mode": "root",
            "expanded_cluster_id": None,
            "snapshot_version": snapshot["version"],
            "built_at": snapshot.get("built_at"),
            "nodes": [_normalize_node(node, snapshot["schema_id"]) for node in snapshot["root_nodes"]],
            "edges": [_normalize_edge(edge, snapshot["schema_id"]) for edge in snapshot["root_edges"]],
            "stats": snapshot["stats"],
            "type_counts": snapshot["type_counts"],
        }
