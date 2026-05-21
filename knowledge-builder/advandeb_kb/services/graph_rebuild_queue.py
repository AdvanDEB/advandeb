"""Graph artifact invalidation and rebuild queue.

Callers mark schemas dirty whenever ingestion or curation mutates the KB.
The background worker rebuilds each schema's full graph artifact out of band.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class GraphRebuildQueue:
    """Tracks graph schemas that need their full graph artifact rebuilt."""

    def __init__(self) -> None:
        self._dirty: set[str] = set()
        self._task: asyncio.Task | None = None
        self._wake_event: asyncio.Event | None = None
        self._stop_event: asyncio.Event | None = None
        self._builder = None

    def mark_dirty(self, schema_name: str) -> None:
        """Mark a schema so the background worker rebuilds its graph artifact."""
        self._dirty.add(schema_name)
        if self._wake_event is not None:
            self._wake_event.set()
        logger.info("GraphRebuildQueue.mark_dirty(%r)", schema_name)

    def is_dirty(self, schema_name: str) -> bool:
        return schema_name in self._dirty

    def clear_dirty(self, schema_name: str) -> None:
        self._dirty.discard(schema_name)

    async def enqueue_rebuild(self, schema_name: str) -> None:
        self.mark_dirty(schema_name)

    async def get_builder(self):
        if self._builder is not None:
            return self._builder

        from app.core.database import get_arango_db, get_database, get_kb_database
        from advandeb_kb.services.graph_artifact_builder import GraphArtifactBuilder

        self._builder = GraphArtifactBuilder(
            get_arango_db(),
            get_kb_database(),
            get_database(),
        )
        await self._builder.ensure_indexes()
        return self._builder

    async def start(self, db: Any = None) -> None:
        """Lifecycle hook kept for main.py compatibility."""
        if self._task is not None and not self._task.done():
            return
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        builder = await self.get_builder()

        # Heal any artifacts that were left in 'building' state by a previous
        # crash / SIGKILL — reset them to 'missing' so they get queued below.
        try:
            store = builder.store
            await store.kb_db[store.META_COLLECTION].update_many(
                {"status": "building"},
                {"$set": {"status": "missing"}},
            )
            logger.info("GraphRebuildQueue: reset stuck 'building' artifacts to 'missing'")
        except Exception:
            logger.exception("GraphRebuildQueue: failed to reset stuck building artifacts")

        meta_map = await builder.list_public_meta_map()
        for schema in builder.query_service.list_schemas():
            if meta_map.get(schema["_id"], {}).get("status") not in ("ready", "stale"):
                self._dirty.add(schema["_id"])
                logger.info("GraphRebuildQueue: queued missing artifact for %s", schema["_id"])
        self._task = asyncio.create_task(self._run(), name="graph-artifact-rebuild-queue")
        logger.info("GraphRebuildQueue: graph artifact rebuild queue active, %d schemas queued", len(self._dirty))

    async def stop(self) -> None:
        """Lifecycle hook."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._wake_event is not None:
            self._wake_event.set()
        if self._task is not None:
            try:
                await self._task
            finally:
                self._task = None
        self._builder = None

    async def _run(self) -> None:
        assert self._wake_event is not None
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            if not self._dirty:
                await self._wake_event.wait()
                self._wake_event.clear()
                continue

            schema_name = sorted(self._dirty)[0]
            self._dirty.discard(schema_name)
            try:
                builder = await self.get_builder()
                logger.info("GraphRebuildQueue: rebuilding artifact for %s", schema_name)
                await builder.build_schema_artifact(schema_name)
            except Exception:
                logger.exception("GraphRebuildQueue: artifact rebuild failed for %s", schema_name)


# Module-level singleton — import this everywhere
graph_rebuild_queue = GraphRebuildQueue()
