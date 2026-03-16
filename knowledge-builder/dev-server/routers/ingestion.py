"""
Ingestion API — PDF upload, batch management, progress streaming.

Endpoints:
  POST /api/ingestion/upload              — upload PDF + start processing
  GET  /api/ingestion/sources             — list PAPERS_ROOT folders
  POST /api/ingestion/scan                — scan folders, create batch+jobs
  POST /api/ingestion/run                 — start processing a pending batch
  GET  /api/ingestion/batches             — list batches
  GET  /api/ingestion/batches/{id}        — get batch detail
  GET  /api/ingestion/batches/{id}/stream — SSE: live job progress
  GET  /api/ingestion/jobs                — list jobs (filterable)
  GET  /api/ingestion/jobs/{id}           — get job detail
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from advandeb_kb.config.settings import settings
from advandeb_kb.database.mongodb import get_database
from advandeb_kb.models.ingestion import IngestionJob
from advandeb_kb.services.ingestion_service import IngestionService
from tasks.pipeline import run_pdf_job, run_batch_worker

router = APIRouter()


async def _get_service() -> IngestionService:
    db = await get_database()
    return IngestionService(db)


# ---------------------------------------------------------------------------
# PDF upload
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    general_domain: Optional[str] = None,
) -> Dict[str, Any]:
    """Upload a single PDF and immediately queue it for ingestion."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    upload_dir = os.path.join(settings.PAPERS_ROOT, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    dest = os.path.join(upload_dir, file.filename)
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    db = await get_database()
    service = IngestionService(db)
    batch = await service.create_batch(["uploads"], general_domain=general_domain)

    job = IngestionJob(
        batch_id=batch.id,
        source_type="pdf_upload",
        source_path_or_url=f"uploads/{file.filename}",
        metadata={"general_domain": general_domain} if general_domain else {},
    )
    await db.ingestion_jobs.insert_one(job.model_dump(by_alias=True))
    await db.ingestion_batches.update_one(
        {"_id": batch.id},
        {"$set": {"num_files": 1, "status": "running", "updated_at": datetime.utcnow()}},
    )

    background_tasks.add_task(run_pdf_job, str(job.id), db)

    return {
        "batch_id": str(batch.id),
        "job_id": str(job.id),
        "filename": file.filename,
        "status": "processing",
    }


# ---------------------------------------------------------------------------
# PAPERS_ROOT browsing
# ---------------------------------------------------------------------------

@router.get("/sources")
async def list_sources() -> Dict[str, Any]:
    """List available source folders under PAPERS_ROOT."""
    root = settings.PAPERS_ROOT
    if not os.path.isdir(root):
        raise HTTPException(status_code=400, detail=f"PAPERS_ROOT does not exist: {root}")

    def count_pdfs(path: str) -> int:
        total = 0
        for _, _, files in os.walk(path):
            total += sum(1 for f in files if f.lower().endswith(".pdf"))
        return total

    entries: List[Dict[str, Any]] = [
        {"path": ".", "name": "root", "pdf_count": count_pdfs(root)}
    ]
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if os.path.isdir(full):
            entries.append({"path": name, "name": name, "pdf_count": count_pdfs(full)})

    return {"root": root, "entries": entries}


# ---------------------------------------------------------------------------
# Batch management
# ---------------------------------------------------------------------------

@router.post("/scan")
async def scan_folders(folders: List[str]) -> Dict[str, Any]:
    """Scan selected folders and create an ingestion batch + jobs."""
    if not folders:
        raise HTTPException(status_code=400, detail="No folders specified")
    db = await get_database()
    service = IngestionService(db)
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
async def run_batch(batch_id: str, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start processing all pending jobs in a batch via a single controlled worker."""
    db = await get_database()
    service = IngestionService(db)
    if not await service.get_batch(batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")

    pending = await db.ingestion_jobs.count_documents(
        {"batch_id": ObjectId(batch_id), "status": "pending"}
    )
    if pending == 0:
        raise HTTPException(status_code=400, detail="No pending jobs in this batch")

    await db.ingestion_jobs.update_many(
        {"batch_id": ObjectId(batch_id), "status": "pending"},
        {"$set": {"status": "queued", "updated_at": datetime.utcnow()}},
    )
    await db.ingestion_batches.update_one(
        {"_id": ObjectId(batch_id)},
        {"$set": {"status": "running", "updated_at": datetime.utcnow()}},
    )
    # Single background task — internally limits concurrency to 3 parallel Ollama calls
    background_tasks.add_task(run_batch_worker, batch_id, db)
    return {"batch_id": batch_id, "jobs_enqueued": pending}


@router.get("/batches")
async def list_batches(limit: int = 20) -> Dict[str, Any]:
    service = await _get_service()
    return {"batches": await service.list_batches(limit=limit)}


@router.get("/batches/{batch_id}/stream")
async def stream_batch_progress(batch_id: str):
    """SSE: streams job progress every 2 s until the batch finishes."""
    async def event_stream():
        db = await get_database()
        oid = ObjectId(batch_id)
        while True:
            jobs = []
            async for job in db.ingestion_jobs.find({"batch_id": oid}):
                jobs.append({
                    "id": str(job["_id"]),
                    "status": job.get("status"),
                    "stage": job.get("stage"),
                    "progress": job.get("progress", 0),
                    "source": job.get("source_path_or_url", ""),
                    "error": job.get("error_message"),
                })
            batch_doc = await db.ingestion_batches.find_one({"_id": oid})
            batch_status = batch_doc.get("status", "unknown") if batch_doc else "unknown"
            yield f"data: {json.dumps({'batch_status': batch_status, 'jobs': jobs})}\n\n"
            if batch_status in ("completed", "failed", "mixed"):
                break
            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: str) -> Dict[str, Any]:
    service = await _get_service()
    batch = await service.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


# ---------------------------------------------------------------------------
# Job queries
# ---------------------------------------------------------------------------

@router.get("/jobs")
async def list_jobs(
    batch_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
) -> Dict[str, Any]:
    service = await _get_service()
    return {
        "jobs": await service.list_jobs(
            batch_id=batch_id, status=status, limit=limit, skip=skip
        )
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    service = await _get_service()
    job = await service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
