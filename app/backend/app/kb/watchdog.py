"""
Ingestion batch watchdog — detects and recovers stuck batches.

Two responsibilities:
1. *Startup scan*: on server start, immediately mark as ``"failed"`` any batch
   that has been in ``"running"`` status for longer than BATCH_TIMEOUT_MINUTES.
   This handles batches that were orphaned by a previous server crash or restart.

2. *Recurring check*: every WATCHDOG_INTERVAL_SECONDS, repeat the same scan so
   that newly-stuck batches are caught without requiring another restart.

A batch is considered "stuck" when:
  - ``status == "running"``  AND
  - ``updated_at`` is older than ``BATCH_TIMEOUT_MINUTES`` ago

When a stuck batch is found, all of its ``running`` and ``queued`` jobs are also
transitioned to ``"failed"`` with an appropriate error message.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# How long (minutes) a batch may stay "running" before being considered stuck.
BATCH_TIMEOUT_MINUTES: int = 30

# How often (seconds) to poll for stuck batches after startup.
WATCHDOG_INTERVAL_SECONDS: int = 300  # 5 minutes


async def recover_stuck_batches(db: AsyncIOMotorDatabase) -> int:
    """
    Mark all stuck batches as ``"failed"`` and their stuck jobs as ``"failed"``.

    Returns the number of batches recovered.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=BATCH_TIMEOUT_MINUTES)
    recovered = 0

    async for batch in db.ingestion_batches.find(
        {"status": "running", "updated_at": {"$lt": cutoff}}
    ):
        batch_id = batch["_id"]
        batch_id_str = str(batch_id)
        age_minutes = (datetime.utcnow() - batch.get("updated_at", datetime.utcnow())).total_seconds() / 60

        logger.warning(
            "Watchdog: batch %s has been running for %.1f minutes — marking failed",
            batch_id_str,
            age_minutes,
        )

        now = datetime.utcnow()

        # Fail all jobs still in an active state for this batch
        await db.ingestion_jobs.update_many(
            {"batch_id": batch_id, "status": {"$in": ["running", "queued", "pending"]}},
            {"$set": {
                "status": "failed",
                "error_message": "batch timed out — recovered by watchdog on server restart",
                "updated_at": now,
            }},
        )

        # Fail the batch itself
        await db.ingestion_batches.update_one(
            {"_id": batch_id},
            {"$set": {"status": "failed", "updated_at": now}},
        )

        recovered += 1

    if recovered:
        logger.info("Watchdog: recovered %d stuck batch(es)", recovered)
    else:
        logger.debug("Watchdog: no stuck batches found")

    return recovered


async def _watchdog_loop(db: AsyncIOMotorDatabase) -> None:
    """Periodically scan for stuck batches. Runs until cancelled."""
    logger.info(
        "Watchdog started — timeout=%d min, interval=%d s",
        BATCH_TIMEOUT_MINUTES,
        WATCHDOG_INTERVAL_SECONDS,
    )
    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
        try:
            await recover_stuck_batches(db)
        except Exception:
            logger.exception("Watchdog: error during stuck-batch scan")


class BatchWatchdog:
    """Lifecycle-managed wrapper around the watchdog coroutine."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self, db: AsyncIOMotorDatabase) -> None:
        """Run the startup scan immediately, then launch the background loop."""
        # Startup scan — runs synchronously before yielding to the server
        try:
            await recover_stuck_batches(db)
        except Exception:
            logger.exception("Watchdog: error during startup scan")

        # Background loop
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
