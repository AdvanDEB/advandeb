"""
KG Builder API — triggers document-taxon linking and exposes stats.

Endpoints:
  GET  /api/kg/stats          — counts for documents, relations, index
  POST /api/kg/link           — enqueue a Celery batch-linking task
  POST /api/kg/link/sync      — run linking synchronously (small batches only)
  PUT  /api/kg/relations/{id} — curator: confirm or reject a suggested relation
"""
from fastapi import APIRouter, Body, HTTPException, Query
from typing import Any, Dict, Literal, Optional

from advandeb_kb.database.mongodb import get_database
from advandeb_kb.services.kg_builder_service import KGBuilderService
from advandeb_kb.services.kg_linker_agent_service import KGLinkerAgentService
from bson import ObjectId

router = APIRouter()


async def _get_service() -> KGBuilderService:
    db = await get_database()
    return KGBuilderService(db)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats", summary="KG builder statistics")
async def get_stats() -> Any:
    """Return counts: total docs, linked docs, total relations, by status."""
    service = await _get_service()
    return await service.get_stats()


# ---------------------------------------------------------------------------
# Async (Celery) linking
# ---------------------------------------------------------------------------

@router.post("/link", summary="Enqueue batch document-taxon linking (async)")
async def enqueue_link(
    root_taxid: int = Query(default=40674, description="NCBI root taxon ID"),
    limit: int = Query(default=1000, ge=1, le=100_000),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
) -> Any:
    """Enqueue a Celery task to link a batch of documents to taxa.

    Use GET /api/kg/stats to monitor progress.
    """
    try:
        from tasks.kg_tasks import link_batch
        task = link_batch.delay(
            root_taxid=root_taxid,
            limit=limit,
            skip=skip,
            overwrite=overwrite,
        )
        return {
            "task_id": task.id,
            "status": "queued",
            "params": {"root_taxid": root_taxid, "limit": limit, "skip": skip},
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Celery unavailable: {e}")


# ---------------------------------------------------------------------------
# Sync linking (small batches, returns result immediately)
# ---------------------------------------------------------------------------

@router.post("/link/sync", summary="Run document-taxon linking synchronously")
async def link_sync(
    root_taxid: int = Query(default=40674),
    limit: int = Query(default=200, ge=1, le=5_000),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
) -> Any:
    """Run document-taxon linking in the current request (no Celery required).

    Suitable for small batches (≤ 5 000 docs). For large imports use POST /link.
    """
    db = await get_database()
    service = KGBuilderService(db)
    await service.ensure_indexes()
    n_indexed = await service.build_name_index(root_taxid=root_taxid)
    result = await service.link_documents(limit=limit, skip=skip, overwrite=overwrite)
    result["index_entries"] = n_indexed
    result["root_taxid"] = root_taxid
    return result


# ---------------------------------------------------------------------------
# Agent linking — sync (small batches, inline result)
# ---------------------------------------------------------------------------

@router.post("/link/agent/sync", summary="Run agent document-taxon linking synchronously")
async def link_agent_sync(
    model: str = Query(default="mistral", description="Ollama model name"),
    limit: int = Query(default=20, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
) -> Any:
    """Run LLM-agent document-taxon linking inline (no Celery required).

    Suitable for small batches (≤ 500 docs). For large imports use POST /link/agent.
    """
    db = await get_database()
    svc = KGLinkerAgentService(db)
    return await svc.link_documents(model=model, limit=limit, skip=skip, overwrite=overwrite)


# ---------------------------------------------------------------------------
# Agent linking — async (Celery)
# ---------------------------------------------------------------------------

@router.post("/link/agent", summary="Enqueue agent document-taxon linking (async)")
async def link_agent_async(
    model: str = Query(default="mistral", description="Ollama model name"),
    limit: int = Query(default=500, ge=1, le=100_000),
    skip: int = Query(default=0, ge=0),
    overwrite: bool = Query(default=False),
) -> Any:
    """Enqueue a Celery task to run the LLM agent on a batch of documents."""
    try:
        from tasks.kg_tasks import link_batch_agent
        task = link_batch_agent.delay(model=model, limit=limit, skip=skip, overwrite=overwrite)
        return {"task_id": task.id, "status": "queued", "params": {"model": model, "limit": limit, "skip": skip}}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Celery unavailable: {e}")


# ---------------------------------------------------------------------------
# Curator: confirm / reject relations
# ---------------------------------------------------------------------------

@router.put("/relations/{relation_id}", summary="Confirm or reject a suggested relation")
async def update_relation(
    relation_id: str,
    body: Dict[str, Any] = Body(default={}),
) -> Any:
    """Set status to 'confirmed' or 'rejected' on a document_taxon_relation.

    Body: { "status": "confirmed" | "rejected", "curator_id": "..." }
    """
    if not ObjectId.is_valid(relation_id):
        raise HTTPException(status_code=400, detail="Invalid relation_id")

    new_status: str = body.get("status", "")
    if new_status not in ("confirmed", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'confirmed' or 'rejected'")

    from datetime import datetime
    db = await get_database()
    result = await db.document_taxon_relations.update_one(
        {"_id": ObjectId(relation_id)},
        {
            "$set": {
                "status": new_status,
                "updated_at": datetime.utcnow(),
                "reviewed_by": body.get("curator_id", "curator"),
            }
        },
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Relation not found")
    return {"updated": True, "status": new_status}


# ---------------------------------------------------------------------------
# Browse relations (for the UI)
# ---------------------------------------------------------------------------

@router.get("/relations", summary="Browse document-taxon relations")
async def list_relations(
    status: Optional[str] = Query(default=None),
    tax_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
) -> Any:
    """Return a page of document_taxon_relations with optional filters."""
    db = await get_database()
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if tax_id is not None:
        query["tax_id"] = tax_id

    from bson import ObjectId as _OID
    from datetime import datetime as _dt

    docs = []
    async for rel in db.document_taxon_relations.find(query, limit=limit, skip=skip):
        rel["_id"] = str(rel["_id"])
        rel["document_id"] = str(rel["document_id"])
        if isinstance(rel.get("created_at"), _dt):
            rel["created_at"] = rel["created_at"].isoformat()
        if isinstance(rel.get("updated_at"), _dt):
            rel["updated_at"] = rel["updated_at"].isoformat()
        docs.append(rel)

    total = await db.document_taxon_relations.count_documents(query)
    return {"total": total, "relations": docs}
