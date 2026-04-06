"""
Ingestion API — PDF upload, batch management, progress streaming.
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from advandeb_kb.config.settings import settings
from advandeb_kb.models.ingestion import IngestionJob
from advandeb_kb.services.ingestion_service import IngestionService
from app.core.auth import verify_token
from app.core.database import get_database as get_main_database, get_kb_database as get_database
from app.core.dependencies import require_curator
from app.kb.pipeline import run_pdf_job, run_batch_worker, cancel_batch

router = APIRouter()


class ScanRequest(BaseModel):
    folders: List[str] = []
    files: List[str] = []          # optional explicit file paths (relative to PAPERS_ROOT)
    general_domain: Optional[str] = None


class RunRequest(BaseModel):
    batch_id: str


async def _get_service() -> IngestionService:
    return IngestionService(get_database())


# SSE streams cannot send custom headers, so we accept the JWT as ?token= query param.
async def _require_curator_sse(
    token: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    jwt_token = token
    if not jwt_token and authorization and authorization.startswith("Bearer "):
        jwt_token = authorization[7:]
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_token(jwt_token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    from bson import ObjectId as ObjId
    db = get_main_database()  # users live in the main app DB, not the KB DB
    user_doc = await db.users.find_one({"_id": ObjId(user_id)})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    roles = user_doc.get("roles", [])
    if not any(r in roles for r in ["administrator", "knowledge_curator"]):
        raise HTTPException(status_code=403, detail="Curator access required")
    return {"id": str(user_doc["_id"]), "roles": roles}


# ---------------------------------------------------------------------------
# PDF upload
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    general_domain: Optional[str] = None,
    current_user: dict = Depends(require_curator),
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

    db = get_database()
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
async def list_sources(
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
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


@router.get("/sources/{folder:path}")
async def list_folder_files(
    folder: str,
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    """Return a recursive tree of subfolders and PDF files under a folder in PAPERS_ROOT."""
    root = settings.PAPERS_ROOT
    folder_path = os.path.join(root, folder) if folder != "." else root
    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=404, detail=f"Folder not found: {folder}")

    def build_tree(abs_path: str) -> Dict[str, Any]:
        files = []
        subdirs = []
        for name in sorted(os.listdir(abs_path)):
            full = os.path.join(abs_path, name)
            if os.path.isfile(full) and name.lower().endswith(".pdf"):
                rel = os.path.relpath(full, root)
                files.append({"path": rel, "name": name, "size": os.path.getsize(full)})
            elif os.path.isdir(full):
                subdirs.append(build_tree(full))
        rel_dir = os.path.relpath(abs_path, root)
        return {
            "path": rel_dir,
            "name": os.path.basename(abs_path),
            "files": files,
            "subdirs": subdirs,
        }

    tree = build_tree(folder_path)
    return {"folder": folder, "tree": tree}

# ---------------------------------------------------------------------------
# Batch management
# ---------------------------------------------------------------------------

@router.post("/scan")
async def scan_folders(
    body: ScanRequest,
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    """Scan selected folders (and/or explicit files) and create an ingestion batch + jobs."""
    if not body.folders and not body.files:
        raise HTTPException(status_code=400, detail="No folders or files specified")
    db = get_database()
    service = IngestionService(db)
    batch = await service.create_batch(body.folders, general_domain=body.general_domain)
    num_files = await service.create_jobs_for_batch(batch, explicit_files=body.files)
    if num_files == 0:
        raise HTTPException(status_code=400, detail="No PDFs found in selected folders/files")
    return {
        "batch_id": str(batch.id),
        "num_files": num_files,
        "folders": body.folders,
        "files": body.files,
        "source_root": batch.source_root,
    }


@router.post("/run")
async def run_batch(
    body: RunRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    """Start processing all pending jobs in a batch."""
    batch_id = body.batch_id
    db = get_database()
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
    background_tasks.add_task(run_batch_worker, batch_id, db)
    return {"batch_id": batch_id, "jobs_enqueued": pending}


@router.get("/batches")
async def list_batches(
    limit: int = 20,
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    service = await _get_service()
    return {"batches": await service.list_batches(limit=limit)}


@router.delete("/batches/{batch_id}")
async def delete_batch(
    batch_id: str,
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    """Delete a batch and all its jobs. Not allowed while the batch is running."""
    service = await _get_service()
    try:
        deleted = await service.delete_batch(batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"deleted": True, "batch_id": batch_id}


@router.post("/batches/{batch_id}/stop")
async def stop_batch(
    batch_id: str,
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    """Stop a running batch. Cancels all queued/running jobs and signals the worker to halt."""
    db = get_database()
    batch_doc = await db.ingestion_batches.find_one({"_id": ObjectId(batch_id)})
    if not batch_doc:
        raise HTTPException(status_code=404, detail="Batch not found")

    terminal_statuses = {"completed", "failed", "mixed", "stopped"}
    if batch_doc.get("status") in terminal_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Batch is already in a terminal state: {batch_doc.get('status')}",
        )

    now = datetime.utcnow()

    # Cancel all jobs that haven't finished yet
    await db.ingestion_jobs.update_many(
        {"batch_id": ObjectId(batch_id), "status": {"$in": ["running", "queued", "pending"]}},
        {"$set": {
            "status": "cancelled",
            "error_message": "batch stopped by user",
            "updated_at": now,
        }},
    )

    # Mark the batch as stopped
    await db.ingestion_batches.update_one(
        {"_id": ObjectId(batch_id)},
        {"$set": {"status": "stopped", "updated_at": now}},
    )

    # Signal the pipeline worker to stop processing jobs for this batch
    cancel_batch(batch_id)

    updated = await db.ingestion_batches.find_one({"_id": ObjectId(batch_id)})
    # Serialise ObjectId fields for JSON response
    if updated:
        updated["_id"] = str(updated["_id"])
        for k, v in updated.items():
            if isinstance(v, datetime):
                updated[k] = v.isoformat()
    return updated or {"batch_id": batch_id, "status": "stopped"}


@router.get("/batches/{batch_id}/stream")
async def stream_batch_progress(
    batch_id: str,
    current_user: dict = Depends(_require_curator_sse),
) -> StreamingResponse:
    """SSE: streams job progress every 2 s until the batch finishes."""
    async def event_stream():
        db = get_database()
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
            if batch_status in ("completed", "failed", "mixed", "stopped"):
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
async def get_batch(
    batch_id: str,
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
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
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    service = await _get_service()
    return {
        "jobs": await service.list_jobs(
            batch_id=batch_id, status=status, limit=limit, skip=skip
        )
    }


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    service = await _get_service()
    job = await service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
