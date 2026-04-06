"""
GraphRebuildQueue — debounced automatic graph rebuild service.

Usage
-----
Import the singleton and mark schemas as dirty from anywhere in the app:

    from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue
    graph_rebuild_queue.mark_dirty("sf_support")
    graph_rebuild_queue.mark_dirty("citation")
    graph_rebuild_queue.mark_dirty("knowledge_graph")

The background worker (started once at app startup) coalesces dirty flags
and rebuilds the affected graph schema(s) once the dirty flag has been set
for at least DEBOUNCE_SECONDS (default 30) without another mark_dirty call.

This avoids hammering the graph builder during a batch ingestion run that
processes hundreds of PDFs — the rebuild only fires when the pipeline goes
quiet.

Start / stop
------------
Call `await graph_rebuild_queue.start(db)` on FastAPI startup and
`await graph_rebuild_queue.stop()` on shutdown.

The `db` argument must be an AsyncIOMotorDatabase instance pointing to the
advandeb operational database (DATABASE_NAME=advandeb).
"""
import asyncio
import logging
import time
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

# How many seconds of idle time (no new mark_dirty calls for that schema)
# before a rebuild is triggered.
DEBOUNCE_SECONDS: float = 30.0

# Default root taxid used for knowledge_graph / taxonomical rebuilds.
DEFAULT_ROOT_TAXID: int = 33208  # Animalia

# Max nodes for the full taxonomical schema rebuild (Animalia subtree).
# Set high to capture broad taxonomic coverage; the UI overview/expand pattern
# handles navigation within the large graph.
TAXONOMY_MAX_NODES: int = 100000


class GraphRebuildQueue:
    """Debounced background service that auto-rebuilds graph schemas."""

    def __init__(self) -> None:
        # schema_name → timestamp of the *last* mark_dirty call
        self._dirty: Dict[str, float] = {}
        # Lock is created lazily inside start() so it is always bound to the
        # correct running event loop (avoids DeprecationWarning / errors when
        # the singleton is created at import time outside a running loop, e.g.
        # with Gunicorn pre-fork workers).
        self._lock: Optional[asyncio.Lock] = None
        self._task: Optional[asyncio.Task] = None
        self._db: Any = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API — call from pipeline / service hooks
    # ------------------------------------------------------------------

    def mark_dirty(self, schema_name: str) -> None:
        """Mark a schema as needing a rebuild.

        Thread-safe (only updates a plain dict + float; GIL protects us).
        Can be called from sync or async code without awaiting.
        """
        self._dirty[schema_name] = time.monotonic()
        logger.debug("GraphRebuildQueue: marked dirty → %s", schema_name)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, db: Any) -> None:
        """Start the background worker.  Call once from FastAPI startup."""
        if self._running:
            logger.warning("GraphRebuildQueue: already running")
            return
        self._db = db
        self._running = True
        # Create the lock here, inside a running event loop, so it is always
        # bound to the correct loop regardless of when the singleton was constructed.
        self._lock = asyncio.Lock()
        self._task = asyncio.create_task(self._worker(), name="graph-rebuild-worker")
        logger.info("GraphRebuildQueue: background worker started (debounce=%.0fs)", DEBOUNCE_SECONDS)

    async def stop(self) -> None:
        """Stop the background worker.  Call from FastAPI shutdown."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("GraphRebuildQueue: background worker stopped")

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    async def _worker(self) -> None:
        while self._running:
            await asyncio.sleep(5)  # poll every 5 seconds

            now = time.monotonic()
            lock = self._lock
            if lock is None:
                continue
            async with lock:
                due: Set[str] = {
                    name
                    for name, ts in list(self._dirty.items())
                    if now - ts >= DEBOUNCE_SECONDS
                }
                for name in due:
                    del self._dirty[name]

            for schema_name in due:
                await self._rebuild(schema_name)

    # ------------------------------------------------------------------
    # Rebuild dispatch
    # ------------------------------------------------------------------

    async def _rebuild(self, schema_name: str) -> None:
        if self._db is None:
            logger.error("GraphRebuildQueue: db not set, cannot rebuild %s", schema_name)
            return

        logger.info("GraphRebuildQueue: rebuilding schema '%s' …", schema_name)
        try:
            from advandeb_kb.services.graph_builder_service import GraphBuilderService
            builder = GraphBuilderService(self._db)
            await builder.seed_schemas()

            schema = await builder.get_schema_by_name(schema_name)
            if schema is None:
                logger.warning("GraphRebuildQueue: schema '%s' not found in DB", schema_name)
                return

            schema_id = schema["_id"]

            if schema_name == "sf_support":
                result = await builder.build_sf_graph(schema_id)

            elif schema_name == "citation":
                result = await builder.build_citation_graph(schema_id)

            elif schema_name == "knowledge_graph":
                result = await builder.build_knowledge_graph(
                    schema_id,
                    root_taxid=DEFAULT_ROOT_TAXID,
                    max_nodes=10000,  # generous cap; strategy fetches only referenced taxa + ancestors
                )

            elif schema_name == "taxonomical":
                result = await builder.build_taxonomy_graph(
                    schema_id,
                    root_taxid=DEFAULT_ROOT_TAXID,
                    max_nodes=TAXONOMY_MAX_NODES,
                )

            elif schema_name == "physiological_process":
                result = await builder.build_physiological_graph(schema_id)

            else:
                logger.warning("GraphRebuildQueue: no rebuild strategy for '%s'", schema_name)
                return

            logger.info(
                "GraphRebuildQueue: '%s' rebuilt — %s",
                schema_name,
                result,
            )

        except Exception:
            logger.exception("GraphRebuildQueue: rebuild of '%s' failed", schema_name)
            # Re-mark dirty so it retries after another debounce cycle
            self.mark_dirty(schema_name)


# Module-level singleton — import this everywhere
graph_rebuild_queue = GraphRebuildQueue()
