"""
KG Builder API — document-taxon linking, stats, curation.

Document-taxon relations are stored as edges in the ArangoDB
`knowledge_graph` edge collection with relation_type='studies'.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query

from app.core.database import get_arango_db
from app.core.dependencies import require_curator
from app.kb.pipeline import run_kg_link_agent, run_kg_link_batch
from advandeb_kb.services.kg_builder_service import KGBuilderService
from advandeb_kb.services.kg_linker_agent_service import KGLinkerAgentService

router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kg-builder-route")


@router.get("/stats")
async def get_stats(current_user: dict = Depends(require_curator)) -> Any:
    arango = get_arango_db()
    return await KGBuilderService(arango).get_stats()


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
    arango = get_arango_db()
    background_tasks.add_task(run_kg_link_batch, arango, root_taxid, limit, skip, overwrite)
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
    arango = get_arango_db()
    svc = KGBuilderService(arango)
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
    arango = get_arango_db()
    background_tasks.add_task(run_kg_link_agent, arango, model, limit, skip, overwrite)
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
    arango = get_arango_db()
    return await KGLinkerAgentService(arango).link_documents(
        model=model, limit=limit, skip=skip, overwrite=overwrite
    )


@router.put("/relations/{relation_key}")
async def update_relation(
    relation_key: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(require_curator),
) -> Any:
    """Update status of a document-taxon relation edge."""
    new_status: str = body.get("status", "")
    if new_status not in ("confirmed", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'confirmed' or 'rejected'")

    arango = get_arango_db()

    def _update():
        col = arango.db.collection("knowledge_graph")
        doc = col.get(relation_key)
        if doc is None:
            return None
        col.update({
            "_key": relation_key,
            "status": new_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_by": body.get("curator_id", current_user.get("id", "curator")),
        })
        return True

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_executor, _update)
    if result is None:
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
    """List document-taxon relation edges from ArangoDB knowledge_graph."""
    arango = get_arango_db()

    def _list():
        filters = ["e.relation_type == 'studies'"]
        bind: Dict[str, Any] = {"skip": skip, "limit": limit}
        if status:
            filters.append("e.status == @status")
            bind["status"] = status
        if tax_id is not None:
            filters.append("e._to == @to_id")
            bind["to_id"] = f"taxa/{tax_id}"
        where = "FILTER " + " AND ".join(filters)

        rows = arango.aql(
            f"""
            FOR e IN knowledge_graph
                {where}
                LIMIT @skip, @limit
                RETURN {{
                    _key: e._key,
                    document_id: PARSE_IDENTIFIER(e._from).key,
                    tax_id: TO_NUMBER(PARSE_IDENTIFIER(e._to).key),
                    relation_type: e.relation_type,
                    confidence: e.confidence,
                    evidence: e.evidence,
                    status: e.status,
                    created_by: e.created_by,
                    created_at: e.created_at,
                    updated_at: e.updated_at
                }}
            """,
            bind,
        )

        count_filters = "FILTER " + " AND ".join(filters.copy())
        count_bind = {k: v for k, v in bind.items() if k not in ("skip", "limit")}
        total_rows = arango.aql(
            f"RETURN LENGTH(FOR e IN knowledge_graph {count_filters} RETURN 1)",
            count_bind,
        )
        total = total_rows[0] if total_rows else 0
        return {"total": total, "relations": rows}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _list)
