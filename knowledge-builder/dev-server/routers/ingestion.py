from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Dict, Any

from advandeb_kb.config.settings import settings
from advandeb_kb.database.mongodb import get_database
from advandeb_kb.services.ingestion_service import IngestionService
from celery_app import celery_app
from tasks.ingestion_tasks import process_pdf_job


router = APIRouter()


async def get_ingestion_service() -> IngestionService:
    db = await get_database()
    return IngestionService(db)


@router.get("/sources")
async def list_sources() -> Dict[str, Any]:
    """List available source folders under PAPERS_ROOT.

    For now this returns a flat listing (root and immediate children)
    with PDF counts, which is enough for a first iteration of the
    select→scan→confirm flow.
    """

    import os

    root = settings.PAPERS_ROOT
    if not os.path.isdir(root):
        raise HTTPException(status_code=400, detail=f"PAPERS_ROOT does not exist: {root}")

    def count_pdfs(path: str) -> int:
        total = 0
        for _, _, files in os.walk(path):
            total += len([f for f in files if f.lower().endswith(".pdf")])
        return total

    entries: List[Dict[str, Any]] = []

    root_count = count_pdfs(root)
    entries.append({"path": ".", "name": "root", "pdf_count": root_count})

    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if os.path.isdir(full):
            entries.append({
                "path": name,
                "name": name,
                "pdf_count": count_pdfs(full),
            })

    return {"root": root, "entries": entries}


@router.post("/scan")
async def scan_folders(
    folders: List[str],
    service: IngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    """Scan selected folders and create an ingestion batch and jobs.

    Folders are interpreted relative to PAPERS_ROOT.
    """

    if not folders:
        raise HTTPException(status_code=400, detail="No folders specified")

    batch = await service.create_batch(folders)
    num_files = await service.create_jobs_for_batch(batch)

    if num_files == 0:
        raise HTTPException(status_code=400, detail="No PDFs found in selected folders")

    return {
        "batch_id": str(batch.id),
        "num_files": num_files,
        "folders": folders,
        "source_root": batch.source_root,
    }


@router.post("/run")
async def run_batch_ingestion(
    batch_id: str,
    service: IngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    """Enqueue Celery tasks for all pending jobs in a batch."""

    from bson import ObjectId

    batch = await service.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    db = await get_database()
    jobs_collection = db.ingestion_jobs
    pending_jobs = jobs_collection.find({"batch_id": ObjectId(batch_id), "status": "pending"})

    enqueued = 0
    async for job in pending_jobs:
        process_pdf_job.delay(str(job["_id"]))
        enqueued += 1
        await jobs_collection.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "queued"}},
        )

    if enqueued == 0:
        raise HTTPException(status_code=400, detail="No pending jobs to run in this batch")

    # Mark batch as running
    from bson import ObjectId as _ObjectId
    from datetime import datetime as _dt

    await db.ingestion_batches.update_one(
        {"_id": _ObjectId(batch_id)},
        {"$set": {"status": "running", "updated_at": _dt.utcnow()}},
    )

    return {"batch_id": batch_id, "jobs_enqueued": enqueued}


@router.get("/batches")
async def list_batches(
    limit: int = 20,
    service: IngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    batches = await service.list_batches(limit=limit)
    return {"batches": batches}


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: str, service: IngestionService = Depends(get_ingestion_service)) -> Dict[str, Any]:
    batch = await service.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.get("/jobs")
async def list_jobs(
    batch_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
    service: IngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    jobs = await service.list_jobs(batch_id=batch_id, status=status, limit=limit, skip=skip)
    return {"jobs": jobs}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, service: IngestionService = Depends(get_ingestion_service)) -> Dict[str, Any]:
    job = await service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
