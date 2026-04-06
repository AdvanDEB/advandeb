"""
KG Builder API — document-taxon linking, stats, curation.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query

from app.core.database import get_kb_database as get_database
from app.core.dependencies import require_curator
from app.kb.pipeline import run_kg_link_agent, run_kg_link_batch
from advandeb_kb.services.kg_builder_service import KGBuilderService
from advandeb_kb.services.kg_linker_agent_service import KGLinkerAgentService

router = APIRouter()


@router.get("/stats")
async def get_stats(current_user: dict = Depends(require_curator)) -> Any:
    db = get_database()
    return await KGBuilderService(db).get_stats()


@router.post("/link")
async def link_async(
    background_tasks: BackgroundTasks,
    root_taxid: int = Query(default=40674),
    limit: int = Query(default=1000, ge=1, le=100_000),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Enqueue batch document-taxon keyword linking (background)."""
    db = get_database()
    background_tasks.add_task(run_kg_link_batch, db, root_taxid, limit, skip, overwrite)
    return {"status": "queued", "params": {"root_taxid": root_taxid, "limit": limit, "skip": skip}}


@router.post("/link/sync")
async def link_sync(
    root_taxid: int = Query(default=40674),
    limit: int = Query(default=200, ge=1, le=5_000),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Run document-taxon keyword linking synchronously (small batches)."""
    db = get_database()
    svc = KGBuilderService(db)
    await svc.ensure_indexes()
    n_indexed = await svc.build_name_index(root_taxid=root_taxid)
    result = await svc.link_documents(limit=limit, skip=skip, overwrite=overwrite)
    result["index_entries"] = n_indexed
    result["root_taxid"] = root_taxid
    return result


@router.post("/link/agent")
async def link_agent_async(
    background_tasks: BackgroundTasks,
    model: str = Query(default="deepseek-r1:latest"),
    limit: int = Query(default=500, ge=1, le=100_000),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Enqueue LLM agent document-taxon linking (background)."""
    db = get_database()
    background_tasks.add_task(run_kg_link_agent, db, model, limit, skip, overwrite)
    return {"status": "queued", "params": {"model": model, "limit": limit, "skip": skip}}


@router.post("/link/agent/sync")
async def link_agent_sync(
    model: str = Query(default="deepseek-r1:latest"),
    limit: int = Query(default=20, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Run LLM agent document-taxon linking synchronously (small batches)."""
    db = get_database()
    return await KGLinkerAgentService(db).link_documents(
        model=model, limit=limit, skip=skip, overwrite=overwrite
    )


@router.put("/relations/{relation_id}")
async def update_relation(
    relation_id: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    if not ObjectId.is_valid(relation_id):
        raise HTTPException(status_code=400, detail="Invalid relation_id")
    new_status: str = body.get("status", "")
    if new_status not in ("confirmed", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'confirmed' or 'rejected'")

    db = get_database()
    result = await db.document_taxon_relations.update_one(
        {"_id": ObjectId(relation_id)},
        {"$set": {
            "status": new_status,
            "updated_at": datetime.utcnow(),
            "reviewed_by": body.get("curator_id", current_user.get("id", "curator")),
        }},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Relation not found")
    return {"updated": True, "status": new_status}


@router.get("/relations")
async def list_relations(
    status: Optional[str] = Query(default=None),
    tax_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_curator),
) -> Any:
    db = get_database()
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if tax_id is not None:
        query["tax_id"] = tax_id

    docs = []
    async for rel in db.document_taxon_relations.find(query, limit=limit, skip=skip):
        rel["_id"] = str(rel["_id"])
        rel["document_id"] = str(rel["document_id"])
        if isinstance(rel.get("created_at"), datetime):
            rel["created_at"] = rel["created_at"].isoformat()
        if isinstance(rel.get("updated_at"), datetime):
            rel["updated_at"] = rel["updated_at"].isoformat()
        docs.append(rel)

    total = await db.document_taxon_relations.count_documents(query)
    return {"total": total, "relations": docs}
