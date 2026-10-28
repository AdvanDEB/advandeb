"""
KB database admin API — inspects and manages ArangoDB KB collections.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from advandeb_kb.backup_guard import (
    NoRecentBackupError, backup_age_hours, latest_backup, require_recent_backup,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import get_arango_db
from app.core.dependencies import require_curator, require_admin

router = APIRouter()
logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kb-db-route")

# Collections that can be cleared by the reset endpoint.
# Keeps taxa, stylized_facts unchanged — only clears derived/ingested data.
_CLEARABLE_ARANGO = [
    "documents",
    "chunks",
    "facts",
    "sf_support",
    "knowledge_graph",
    "citations",
    "chunk_belongs_to",
    "provenance_traces",
]


@router.get("/review-queues")
async def review_queues(
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    """Counts of pipeline output awaiting human review.

    The Suggestions tab only ever listed *user submissions*
    (``document_submissions`` / ``fact_submissions`` / ``sf_submissions``),
    which are empty — so it showed nothing while tens of thousands of
    machine-generated items sat unreviewed and invisible. These are those items.
    """
    arango = get_arango_db()

    def _counts():
        def n(aql: str) -> int:
            rows = arango.aql(aql, {})
            return rows[0] if rows else 0

        return {
            "facts_pending": n("RETURN LENGTH(FOR f IN facts FILTER f.status == 'pending' RETURN 1)"),
            "facts_total": n("RETURN LENGTH(facts)"),
            "sf_support_suggested": n(
                "RETURN LENGTH(FOR e IN sf_support FILTER e.status == 'suggested' RETURN 1)"
            ),
            "sf_support_total": n("RETURN LENGTH(sf_support)"),
            "studies_suggested": n(
                "RETURN LENGTH(FOR e IN knowledge_graph "
                "FILTER e.relation_type == 'studies' AND e.status == 'suggested' RETURN 1)"
            ),
            "studies_confirmed": n(
                "RETURN LENGTH(FOR e IN knowledge_graph "
                "FILTER e.relation_type == 'studies' AND e.status == 'confirmed' RETURN 1)"
            ),
            "documents_off_domain": n(
                "RETURN LENGTH(FOR d IN documents FILTER d.domain_relevant == false RETURN 1)"
            ),
            "documents_gated": n(
                "RETURN LENGTH(FOR d IN documents FILTER d.domain_relevant != null RETURN 1)"
            ),
        }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _counts)


@router.get("/reset/preview")
async def preview_reset(
    current_user: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Report exactly what a reset would clear, with current row counts.

    Exists so the confirmation dialog can be generated from the same
    ``_CLEARABLE_ARANGO`` list the reset actually uses. The dialog previously
    hardcoded its own description and had drifted out of step — it warned about
    "graph nodes" and "ingestion jobs" (neither is touched) and named
    "taxonomy_nodes" (the collection is ``taxa``). For an irreversible action
    the description must come from the code that performs it.
    """
    arango = get_arango_db()

    def _preview():
        clears = []
        for name in _CLEARABLE_ARANGO:
            if arango.db.has_collection(name):
                clears.append({"name": name, "count": arango.db.collection(name).count()})
        kept = [
            {"name": name, "count": arango.db.collection(name).count()}
            for name in ("taxa", "stylized_facts")
            if arango.db.has_collection(name)
        ]
        return {
            "clears": clears,
            "keeps": kept,
            "total_rows": sum(c["count"] for c in clears),
            "database": arango.db.name,
            "latest_backup": _backup_summary(arango.db.name),
            "max_backup_age_hours": settings.KB_RESET_MAX_BACKUP_AGE_HOURS,
        }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _preview)


def _backup_summary(db_name: str) -> Optional[Dict[str, Any]]:
    manifest = latest_backup(f"arango:{db_name}")
    if manifest is None:
        return None
    return {
        "path": manifest["_path"],
        "finished_at": manifest.get("finished_at"),
        "age_hours": round(backup_age_hours(manifest), 1),
    }


class ResetRequest(BaseModel):
    # The database name, typed back by the admin. A click alone must not be
    # enough to truncate the canonical store.
    confirm: str


@router.post("/reset")
async def reset_knowledge_base(
    body: ResetRequest,
    current_user: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Clear all mutable KB data, keeping taxa and stylized_facts.

    Requires the administrator role, the database name typed back, and a
    backup of this database newer than KB_RESET_MAX_BACKUP_AGE_HOURS — the
    truncation cannot be undone any other way.
    """
    arango = get_arango_db()
    db_name = arango.db.name
    if body.confirm != db_name:
        raise HTTPException(
            status_code=400,
            detail=f"Confirmation does not match: type the database name {db_name!r}.",
        )
    try:
        backup = require_recent_backup(
            f"arango:{db_name}", settings.KB_RESET_MAX_BACKUP_AGE_HOURS)
    except NoRecentBackupError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    logger.warning("KB reset of %s by user %s; restore point %s",
                   db_name, current_user.get("id") or current_user.get("email"), backup["_path"])

    def _reset():
        result: Dict[str, int] = {}
        for name in _CLEARABLE_ARANGO:
            if arango.db.has_collection(name):
                col = arango.db.collection(name)
                count = col.count()
                col.truncate()
                result[name] = count
        return result

    loop = asyncio.get_running_loop()
    deleted = await loop.run_in_executor(_executor, _reset)
    return {"status": "ok", "cleared": deleted, "restore_point": backup["_path"]}


@router.get("/collections")
async def list_collections(
    current_user: dict = Depends(require_curator),
) -> List[Dict[str, Any]]:
    """List all ArangoDB KB collections with document counts."""
    arango = get_arango_db()

    def _list():
        cols = [c for c in arango.db.collections() if not c["name"].startswith("_")]
        result = []
        for c in sorted(cols, key=lambda x: x["name"]):
            name = c["name"]
            count = arango.db.collection(name).count()
            result.append({"name": name, "count": count, "type": c["type"]})
        return result

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _list)


@router.get("/{collection}")
async def get_collection_docs(
    collection: str,
    limit: int = Query(default=20, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_curator),
) -> List[Dict[str, Any]]:
    """Sample documents from an ArangoDB collection."""
    arango = get_arango_db()

    def _sample():
        if not arango.db.has_collection(collection):
            return None
        rows = arango.aql(
            "FOR doc IN @@col LIMIT @skip, @limit RETURN UNSET(doc, '_rev')",
            {"@col": collection, "skip": skip, "limit": limit},
        )
        return rows

    loop = asyncio.get_running_loop()
    docs = await loop.run_in_executor(_executor, _sample)

    if docs is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection}' not found")
    return docs
