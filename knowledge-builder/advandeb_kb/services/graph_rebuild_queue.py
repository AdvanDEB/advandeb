"""Graph artifact invalidation and rebuild queue.

Callers mark schemas dirty whenever ingestion or curation mutates the KB.
The background worker rebuilds each schema's full graph artifact out of band.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Fallback defaults, used when the app config is not importable (e.g. the KB
# library is exercised standalone). When running inside the app these are
# overridden by GRAPH_ARTIFACT_REBUILD_* in app.core.config.settings.
#
# SETTLE coalesces a burst of mark_dirty() calls into a single rebuild;
# MIN_INTERVAL is the floor between two rebuilds of the *same* schema. Without
# pacing, callers that mark a schema dirty on every request (e.g. chat marking
# "chatbot" dirty per message) drive the worker into back-to-back full-graph
# rebuilds — each one loads the entire graph and runs a force layout, pinning a
# CPU and ratcheting RSS as the allocator never returns the transient buffers.
SETTLE_DELAY_SECONDS = 5.0
MIN_REBUILD_INTERVAL_SECONDS = 120.0


def _load_pacing() -> tuple[float, float]:
    """Return (settle_seconds, min_interval_seconds) from app config, or defaults."""
    settle, min_interval = SETTLE_DELAY_SECONDS, MIN_REBUILD_INTERVAL_SECONDS
    try:
        from app.core.config import settings as _s

        settle = float(getattr(_s, "GRAPH_ARTIFACT_REBUILD_SETTLE_SECONDS", settle))
        min_interval = float(
            getattr(_s, "GRAPH_ARTIFACT_REBUILD_MIN_INTERVAL_SECONDS", min_interval)
        )
    except Exception:
        pass
    return settle, min_interval


class GraphRebuildQueue:
    """Tracks graph schemas that need their full graph artifact rebuilt."""

    def __init__(self) -> None:
        self._dirty: set[str] = set()
        self._task: asyncio.Task | None = None
        self._wake_event: asyncio.Event | None = None
        self._stop_event: asyncio.Event | None = None
        self._builder = None
        # schema_name -> monotonic timestamp of its last rebuild start
        self._last_built: dict[str, float] = {}
        # Pacing — resolved from app config in start(); defaults until then.
        self._settle_delay: float = SETTLE_DELAY_SECONDS
        self._min_rebuild_interval: float = MIN_REBUILD_INTERVAL_SECONDS

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
        self._settle_delay, self._min_rebuild_interval = _load_pacing()
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
        logger.info(
            "GraphRebuildQueue: graph artifact rebuild queue active, %d schemas queued "
            "(settle=%.1fs, min_interval=%.1fs)",
            len(self._dirty), self._settle_delay, self._min_rebuild_interval,
        )

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

    async def _sleep_or_stop(self, seconds: float) -> None:
        """Sleep for ``seconds`` but wake early (and return) if stop is requested."""
        if seconds <= 0:
            return
        assert self._stop_event is not None
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _run(self) -> None:
        assert self._wake_event is not None
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            if not self._dirty:
                await self._wake_event.wait()
                self._wake_event.clear()
                # Coalesce a burst of mark_dirty() calls into one rebuild.
                await self._sleep_or_stop(self._settle_delay)
                continue

            # Only rebuild schemas whose per-schema cooldown has elapsed.
            now = time.monotonic()
            ready = [
                s for s in self._dirty
                if now - self._last_built.get(s, 0.0) >= self._min_rebuild_interval
            ]
            if not ready:
                # Everything dirty is still cooling down — wait until the
                # earliest one becomes eligible instead of spinning.
                soonest = min(
                    self._last_built.get(s, 0.0) + self._min_rebuild_interval
                    for s in self._dirty
                )
                await self._sleep_or_stop(max(0.0, soonest - now))
                continue

            schema_name = sorted(ready)[0]
            self._dirty.discard(schema_name)
            # Record the start time *before* building so marks that arrive
            # during the (possibly long) rebuild respect the cooldown.
            self._last_built[schema_name] = time.monotonic()
            try:
                builder = await self.get_builder()
                logger.info("GraphRebuildQueue: rebuilding artifact for %s", schema_name)
                await builder.build_schema_artifact(schema_name)
            except Exception:
                logger.exception("GraphRebuildQueue: artifact rebuild failed for %s", schema_name)


# Module-level singleton — import this everywhere
graph_rebuild_queue = GraphRebuildQueue()
