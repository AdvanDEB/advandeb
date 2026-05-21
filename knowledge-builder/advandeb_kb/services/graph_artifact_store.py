"""Storage helpers for prebuilt graph artifacts.

Metadata is stored in MongoDB while artifact payloads are stored as compressed
JSON files on the local filesystem.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional


GRAPH_ARTIFACT_FORMAT = "advandeb-graph-artifact"
GRAPH_ARTIFACT_FORMAT_VERSION = 1


class GraphArtifactStore:
    META_COLLECTION = "graph_artifact_meta"

    def __init__(self, kb_db: Any, artifact_root: str | Path):
        self.kb_db = kb_db
        self.artifact_root = Path(artifact_root).expanduser().resolve()

    async def ensure_indexes(self) -> None:
        await self.kb_db[self.META_COLLECTION].create_index(
            "schema_id",
            unique=True,
            name="graph_artifact_meta_schema_id",
        )
        await self.kb_db[self.META_COLLECTION].create_index(
            "status",
            name="graph_artifact_meta_status",
        )

    def normalize_meta(self, schema_id: str, schema_name: Optional[str], doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not doc:
            return {
                "schema_id": schema_id,
                "schema_name": schema_name or schema_id,
                "format": GRAPH_ARTIFACT_FORMAT,
                "format_version": GRAPH_ARTIFACT_FORMAT_VERSION,
                "build_id": "",
                "source_revision": "",
                "status": "missing",
                "built_at": None,
                "layout_name": None,
                "node_count": 0,
                "edge_count": 0,
                "density": 0.0,
                "type_counts": {"node_types": {}, "edge_types": {}},
                "bounds_2d": {"min_x": 0.0, "max_x": 0.0, "min_y": 0.0, "max_y": 0.0},
                "size_bytes": 0,
                "sha256": "",
                "storage_path": "",
                "error": None,
            }

        artifact = doc.get("artifact") or {}
        bounds = artifact.get("bounds_2d") or {}
        return {
            "schema_id": doc.get("schema_id", schema_id),
            "schema_name": doc.get("schema_name", schema_name or schema_id),
            "format": doc.get("format", GRAPH_ARTIFACT_FORMAT),
            "format_version": doc.get("format_version", GRAPH_ARTIFACT_FORMAT_VERSION),
            "build_id": artifact.get("build_id", doc.get("build_id", "")),
            "source_revision": artifact.get("source_revision", doc.get("source_revision", "")),
            "status": doc.get("status", "missing"),
            "built_at": artifact.get("built_at"),
            "layout_name": artifact.get("layout_name"),
            "node_count": artifact.get("node_count", 0),
            "edge_count": artifact.get("edge_count", 0),
            "density": artifact.get("density", 0.0),
            "type_counts": artifact.get("type_counts", {"node_types": {}, "edge_types": {}}),
            "bounds_2d": {
                "min_x": bounds.get("min_x", 0.0),
                "max_x": bounds.get("max_x", 0.0),
                "min_y": bounds.get("min_y", 0.0),
                "max_y": bounds.get("max_y", 0.0),
            },
            "size_bytes": artifact.get("size_bytes", 0),
            "sha256": artifact.get("sha256", ""),
            "storage_path": artifact.get("storage_path", ""),
            "error": doc.get("error"),
        }

    async def get_meta_doc(self, schema_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_indexes()
        return await self.kb_db[self.META_COLLECTION].find_one({"_id": schema_id})

    async def get_public_meta(self, schema_id: str, schema_name: Optional[str] = None) -> Dict[str, Any]:
        doc = await self.get_meta_doc(schema_id)
        return self.normalize_meta(schema_id, schema_name, doc)

    async def list_public_meta_map(self) -> Dict[str, Dict[str, Any]]:
        await self.ensure_indexes()
        result: Dict[str, Dict[str, Any]] = {}
        async for doc in self.kb_db[self.META_COLLECTION].find({}):
            schema_id = doc.get("schema_id") or doc.get("_id")
            if not schema_id:
                continue
            result[schema_id] = self.normalize_meta(schema_id, doc.get("schema_name"), doc)
        return result

    async def mark_status(
        self,
        schema_id: str,
        schema_name: str,
        status: str,
        *,
        build_id: str = "",
        source_revision: str = "",
        error: Optional[str] = None,
    ) -> None:
        await self.ensure_indexes()
        await self.kb_db[self.META_COLLECTION].update_one(
            {"_id": schema_id},
            {
                "$set": {
                    "schema_id": schema_id,
                    "schema_name": schema_name,
                    "format": GRAPH_ARTIFACT_FORMAT,
                    "format_version": GRAPH_ARTIFACT_FORMAT_VERSION,
                    "status": status,
                    "build_id": build_id,
                    "source_revision": source_revision,
                    "error": error,
                }
            },
            upsert=True,
        )

    async def publish_artifact(
        self,
        schema_id: str,
        schema_name: str,
        meta: Dict[str, Any],
    ) -> None:
        await self.ensure_indexes()
        await self.kb_db[self.META_COLLECTION].update_one(
            {"_id": schema_id},
            {
                "$set": {
                    "schema_id": schema_id,
                    "schema_name": schema_name,
                    "format": GRAPH_ARTIFACT_FORMAT,
                    "format_version": GRAPH_ARTIFACT_FORMAT_VERSION,
                    "status": "ready",
                    "build_id": meta.get("build_id", ""),
                    "source_revision": meta.get("source_revision", ""),
                    "error": None,
                    "artifact": meta,
                }
            },
            upsert=True,
        )

    async def write_artifact_payload(
        self,
        schema_id: str,
        build_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(self._write_artifact_payload_sync, schema_id, build_id, payload)

    def resolve_storage_path(self, storage_path: str) -> Path:
        path = Path(storage_path)
        if path.is_absolute():
            return path
        return (self.artifact_root / path).resolve()

    def _write_artifact_payload_sync(
        self,
        schema_id: str,
        build_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        schema_dir = self.artifact_root / schema_id
        schema_dir.mkdir(parents=True, exist_ok=True)

        relative_path = Path(schema_id) / f"{build_id}.json.gz"
        final_path = self.artifact_root / relative_path
        temp_path = schema_dir / f"{build_id}.json.gz.tmp"

        raw_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        compressed_bytes = gzip.compress(raw_bytes, compresslevel=6)
        sha256 = hashlib.sha256(compressed_bytes).hexdigest()

        temp_path.write_bytes(compressed_bytes)
        temp_path.replace(final_path)

        return {
            "storage_path": str(relative_path),
            "size_bytes": len(compressed_bytes),
            "sha256": sha256,
        }
