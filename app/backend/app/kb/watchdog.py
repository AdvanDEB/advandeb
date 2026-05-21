"""
Ingestion batch watchdog — detects orphaned batches after a server crash.

On startup, any batch that was left in ``"running"`` status from a *previous*
server process is considered orphaned and its jobs are reset to ``"pending"``
so they can be retried.  The watchdog does NOT impose any time limit on how
long a batch may run — large batches with LLM processing can legitimately take
many hours and must never be killed by an arbitrary timeout.

A batch is considered orphaned (and recoverable) only on server startup, when
we know the previous process is gone.  During normal operation the watchdog
merely logs a warning if a batch has been running for an unusually long time,
but takes no destructive action.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# How often (seconds) to log a warning about long-running batches.
WATCHDOG_INTERVAL_SECONDS: int = 300  # 5 minutes

# How long (minutes) before we start warning about a long-running batch.
# This is purely informational — no action is taken.
WARN_AFTER_MINUTES: int = 60


async def recover_orphaned_batches(db: AsyncIOMotorDatabase) -> int:
    """
    Called once on server startup.  Resets any batch that was left in
    ``"running"`` status by a previous (now-dead) server process.

    Jobs are reset to ``"pending"`` so they can be retried immediately by
    clicking Run again.  Returns the number of batches recovered.
    """
    recovered = 0

    async for batch in db.ingestion_batches.find({"status": "running"}):
        batch_id = batch["_id"]
        batch_id_str = str(batch_id)
        age_minutes = (datetime.utcnow() - batch.get("updated_at", datetime.utcnow())).total_seconds() / 60

        logger.warning(
            "Watchdog [startup]: batch %s was left running (%.1f min) by previous process — resetting jobs to pending",
            batch_id_str,
            age_minutes,
        )

        now = datetime.utcnow()

        # Reset active jobs to pending so they can be retried
        await db.ingestion_jobs.update_many(
            {"batch_id": batch_id, "status": {"$in": ["running", "queued"]}},
            {"$set": {
                "status": "pending",
                "stage": "pending",
                "error_message": "server restarted — job reset to pending for retry",
                "updated_at": now,
            }},
        )

        # Mark batch as mixed/failed so user sees it needs to be re-run
        await db.ingestion_batches.update_one(
            {"_id": batch_id},
            {"$set": {"status": "mixed", "updated_at": now}},
        )

        recovered += 1

    if recovered:
        logger.info("Watchdog [startup]: recovered %d orphaned batch(es) — click Run to retry", recovered)
    else:
        logger.debug("Watchdog [startup]: no orphaned batches found")

    return recovered


async def _watchdog_loop(db: AsyncIOMotorDatabase) -> None:
    """Periodically log warnings about long-running batches. Never kills them."""
    logger.info("Watchdog started — warn_after=%d min, interval=%d s (no destructive timeouts)",
                WARN_AFTER_MINUTES, WATCHDOG_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=WARN_AFTER_MINUTES)
            async for batch in db.ingestion_batches.find(
                {"status": "running", "updated_at": {"$lt": cutoff}}
            ):
                age_minutes = (datetime.utcnow() - batch.get("updated_at", datetime.utcnow())).total_seconds() / 60
                logger.info(
                    "Watchdog: batch %s still running after %.1f minutes (this is normal for large batches)",
                    str(batch["_id"]),
                    age_minutes,
                )
        except Exception:
            logger.exception("Watchdog: error during running-batch scan")


class BatchWatchdog:
    """Lifecycle-managed wrapper around the watchdog coroutine."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self, db: AsyncIOMotorDatabase) -> None:
        """Run the startup orphan recovery, then launch the background loop."""
        try:
            await recover_orphaned_batches(db)
        except Exception:
            logger.exception("Watchdog: error during startup scan")

        self._task = asyncio.create_task(
            _watchdog_loop(db), name="ingestion-watchdog"
        )

    async def stop(self) -> None:
        """Cancel the background loop gracefully."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Watchdog stopped")


# Module-level singleton — imported by main.py
batch_watchdog = BatchWatchdog()
