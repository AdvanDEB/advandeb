"""
KB database admin API — inspects and manages ArangoDB KB collections.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

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


@router.post("/reset")
async def reset_knowledge_base(
    current_user: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Clear all mutable KB data, keeping taxa and stylized_facts.

    Requires administrator role.
    """
    arango = get_arango_db()

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
    return {"status": "ok", "cleared": deleted}


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
