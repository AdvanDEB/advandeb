"""
Job- and batch-status helpers of the ingestion pipeline (app/kb/pipeline.py).

Ported from knowledge-builder/tests/test_ingestion.py, which tested the Celery
versions of these helpers (tasks.ingestion_tasks). Celery was replaced by the
BackgroundTasks pipeline here, and the helpers became async. The database is a
mock throughout: nothing connects to MongoDB or ArangoDB.
"""
import inspect
from unittest.mock import AsyncMock, MagicMock

from bson import ObjectId

from app.kb import pipeline


async def _aiter(items):
    for item in items:
        yield item


def _db_with_job_statuses(statuses):
    """Mock database whose ingestion_jobs hold jobs with these statuses.

    None of the jobs has a document_id, so a finished batch schedules no
    taxonomy linking (which would otherwise reach for ArangoDB).
    """
    def find(query, projection=None):
        if "document_id" in query:
            return _aiter([])
        return _aiter([{"status": s} for s in statuses])

    db = MagicMock()
    db.ingestion_jobs.find.side_effect = find
    db.ingestion_batches.update_one = AsyncMock()
    return db


def test_extract_pdf_text_is_sync():
    """_extract_pdf_text is CPU-bound and is meant to run in a worker thread."""
    assert not inspect.iscoroutinefunction(pipeline._extract_pdf_text)


async def test_set_job_stage_fields():
    db = MagicMock()
    db.ingestion_jobs.update_one = AsyncMock()
    oid = ObjectId()

    await pipeline._set_job_stage(db, oid, "fact_extraction", status="running", progress=30)

    db.ingestion_jobs.update_one.assert_awaited_once()
    filter_, update = db.ingestion_jobs.update_one.call_args[0]
    fields = update["$set"]
    assert filter_ == {"_id": oid}
    assert fields["stage"] == "fact_extraction"
    assert fields["status"] == "running"
    assert fields["progress"] == 30
    assert "updated_at" in fields
    assert "error_message" not in fields


async def test_update_batch_status_completed():
    db = _db_with_job_statuses(["completed", "completed"])
    batch_id = ObjectId()

    await pipeline._update_batch_status(db, batch_id)

    db.ingestion_batches.update_one.assert_awaited_once()
    filter_, update = db.ingestion_batches.update_one.call_args[0]
    assert filter_ == {"_id": batch_id}
    assert update["$set"]["status"] == "completed"


async def test_update_batch_status_mixed():
    db = _db_with_job_statuses(["completed", "failed"])

    await pipeline._update_batch_status(db, ObjectId())

    assert db.ingestion_batches.update_one.call_args[0][1]["$set"]["status"] == "mixed"


async def test_update_batch_status_still_running():
    """A batch is not finalised while any of its jobs is still running."""
    db = _db_with_job_statuses(["completed", "running"])

    await pipeline._update_batch_status(db, ObjectId())

    db.ingestion_batches.update_one.assert_not_called()
