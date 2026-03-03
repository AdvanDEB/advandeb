"""
Tests for IngestionService and ingestion_tasks helpers.

These tests cover import correctness, model field propagation, and the
SF matching logic — all without requiring a live MongoDB or Celery worker.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_KB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_KB_ROOT))
# dev-server path needed so `from celery_app import ...` and `from tasks.xxx` work
sys.path.insert(0, str(_KB_ROOT / "dev-server"))

from bson import ObjectId
from advandeb_kb.models.ingestion import IngestionBatch, IngestionJob
from advandeb_kb.models.knowledge import Document, Fact, FactSFRelation


def test_ingestion_batch_carries_domain():
    batch = IngestionBatch(
        source_root="/data/papers",
        folders=["reproduction"],
        general_domain="reproduction",
        name="Test Batch",
    )
    assert batch.general_domain == "reproduction"
    assert batch.status == "pending"
    data = batch.model_dump(by_alias=True)
    assert data["general_domain"] == "reproduction"
    print("  IngestionBatch domain propagation OK")


def test_ingestion_job_metadata_domain():
    batch = IngestionBatch(source_root="/data", folders=["x"])
    job = IngestionJob(
        batch_id=batch.id,
        source_type="pdf_local",
        source_path_or_url="x/paper.pdf",
        metadata={"general_domain": "reproduction"},
    )
    assert job.metadata["general_domain"] == "reproduction"
    print("  IngestionJob metadata domain OK")


def test_document_model_fields():
    """Verify Document uses the new field names (not the old filename/file_type)."""
    doc = Document(
        title="paper.pdf",
        source_type="pdf_local",
        source_path="reproduction/paper.pdf",
        general_domain="reproduction",
        processing_status="processing",
    )
    assert doc.title == "paper.pdf"
    assert doc.source_path == "reproduction/paper.pdf"
    assert not hasattr(doc, "filename")
    assert not hasattr(doc, "file_type")
    print("  Document new field names OK")


def test_fact_has_document_id():
    """Verify Fact links to a document via document_id (not source string)."""
    doc = Document(title="src.pdf", source_type="pdf_local")
    fact = Fact(
        content="Metabolic rate scales with body mass.",
        document_id=doc.id,
        general_domain="metabolism",
        confidence=0.8,
        tags=["pdf", "extracted"],
    )
    assert fact.document_id == doc.id
    assert fact.general_domain == "metabolism"
    assert not hasattr(fact, "source")
    print("  Fact document_id linkage OK")


def test_fact_sf_relation_defaults():
    """New relations should default to suggested status."""
    fact = Fact(content="x", document_id=ObjectId())
    sf_id = ObjectId()
    rel = FactSFRelation(
        fact_id=fact.id, sf_id=sf_id,
        relation_type="supports", confidence=0.45,
    )
    assert rel.status == "suggested"
    assert rel.created_by == "agent"
    print("  FactSFRelation defaults OK")


def test_extract_pdf_text_runs_in_thread():
    """_extract_pdf_text should be a plain sync function (not async)."""
    from tasks.ingestion_tasks import _extract_pdf_text
    import inspect
    assert not inspect.iscoroutinefunction(_extract_pdf_text)
    print("  _extract_pdf_text is sync OK")


def test_set_job_stage_fields():
    """_set_job_stage should update stage, status, progress, and updated_at."""
    from tasks.ingestion_tasks import _set_job_stage

    jobs_mock = MagicMock()
    oid = ObjectId()
    _set_job_stage(jobs_mock, oid, "fact_extraction", status="running", progress=30)

    jobs_mock.update_one.assert_called_once()
    call_args = jobs_mock.update_one.call_args
    filter_ = call_args[0][0]
    update = call_args[0][1]["$set"]

    assert filter_ == {"_id": oid}
    assert update["stage"] == "fact_extraction"
    assert update["status"] == "running"
    assert update["progress"] == 30
    assert "updated_at" in update
    assert "error_message" not in update
    print("  _set_job_stage OK")


def test_update_batch_status_completed():
    """Batch should be marked completed when all jobs are done."""
    from tasks.ingestion_tasks import _update_batch_status

    batch_id = ObjectId()
    db = MagicMock()
    db.ingestion_jobs.find.return_value = [
        {"status": "completed"},
        {"status": "completed"},
    ]
    _update_batch_status(db, batch_id)

    db.ingestion_batches.update_one.assert_called_once()
    set_fields = db.ingestion_batches.update_one.call_args[0][1]["$set"]
    assert set_fields["status"] == "completed"
    print("  _update_batch_status completed OK")


def test_update_batch_status_mixed():
    from tasks.ingestion_tasks import _update_batch_status

    batch_id = ObjectId()
    db = MagicMock()
    db.ingestion_jobs.find.return_value = [
        {"status": "completed"},
        {"status": "failed"},
    ]
    _update_batch_status(db, batch_id)
    set_fields = db.ingestion_batches.update_one.call_args[0][1]["$set"]
    assert set_fields["status"] == "mixed"
    print("  _update_batch_status mixed OK")


def test_update_batch_status_still_running():
    """Should not update batch while jobs are still running."""
    from tasks.ingestion_tasks import _update_batch_status

    batch_id = ObjectId()
    db = MagicMock()
    db.ingestion_jobs.find.return_value = [
        {"status": "completed"},
        {"status": "running"},
    ]
    _update_batch_status(db, batch_id)
    db.ingestion_batches.update_one.assert_not_called()
    print("  _update_batch_status still_running skips OK")


def test_pdf_discovery_in_folders():
    """create_jobs_for_batch should discover PDFs recursively."""
    import asyncio
    from unittest.mock import AsyncMock

    with tempfile.TemporaryDirectory() as tmpdir:
        sub = Path(tmpdir) / "reproduction"
        sub.mkdir()
        (sub / "paper1.pdf").write_bytes(b"%PDF-1.4")
        (sub / "notes.txt").write_bytes(b"not a pdf")
        nested = sub / "nested"
        nested.mkdir()
        (nested / "paper2.pdf").write_bytes(b"%PDF-1.4")

        # Minimal mock of AsyncIOMotorDatabase
        db_mock = MagicMock()
        db_mock.ingestion_jobs.insert_many = AsyncMock()
        db_mock.ingestion_batches.update_one = AsyncMock()

        from advandeb_kb.services.ingestion_service import IngestionService
        svc = IngestionService(db_mock)

        batch = IngestionBatch(
            source_root=tmpdir,
            folders=["reproduction"],
            general_domain="reproduction",
        )

        count = asyncio.run(svc.create_jobs_for_batch(batch))
        assert count == 2

        inserted = db_mock.ingestion_jobs.insert_many.call_args[0][0]
        assert len(inserted) == 2
        paths = {j["source_path_or_url"] for j in inserted}
        assert all(p.endswith(".pdf") for p in paths)
        # domain carried in metadata
        for j in inserted:
            assert j["metadata"].get("general_domain") == "reproduction"

    print("  PDF discovery in folders OK")


if __name__ == "__main__":
    tests = [
        test_ingestion_batch_carries_domain,
        test_ingestion_job_metadata_domain,
        test_document_model_fields,
        test_fact_has_document_id,
        test_fact_sf_relation_defaults,
        test_extract_pdf_text_runs_in_thread,
        test_set_job_stage_fields,
        test_update_batch_status_completed,
        test_update_batch_status_mixed,
        test_update_batch_status_still_running,
        test_pdf_discovery_in_folders,
    ]
    print(f"Running {len(tests)} ingestion tests...")
    for t in tests:
        t()
    print(f"\nAll {len(tests)} tests passed.")
