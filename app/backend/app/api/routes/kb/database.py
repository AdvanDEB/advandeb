from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Any, Dict, List
from bson import ObjectId
from datetime import datetime

from app.core.database import get_kb_database as get_database
from app.core.dependencies import require_curator, require_admin

router = APIRouter()


def _serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = _serialize_doc(v)
        elif isinstance(v, list):
            out[k] = [_serialize_item(i) for i in v]
        else:
            out[k] = v
    return out


def _serialize_item(item: Any) -> Any:
    if isinstance(item, ObjectId):
        return str(item)
    elif isinstance(item, datetime):
        return item.isoformat()
    elif isinstance(item, dict):
        return _serialize_doc(item)
    return item


@router.post("/reset")
async def reset_knowledge_base(
    current_user: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Clear all mutable KB data, keeping taxonomy_nodes, stylized_facts, and graph_schemas.

    Requires administrator role.
    """
    db = get_database()
    _CLEARABLE = [
        "documents",
        "chunks",
        "facts",
        "fact_sf_relations",
        "document_taxon_relations",
        "graph_nodes",
        "graph_edges",
        "ingestion_batches",
        "ingestion_jobs",
    ]
    result: Dict[str, int] = {}
    for coll in _CLEARABLE:
        r = await db[coll].delete_many({})
        result[coll] = r.deleted_count
    return {"status": "ok", "deleted": result}


@router.get("/collections")
async def list_collections(
    current_user: dict = Depends(require_curator),
) -> List[Dict[str, Any]]:
    """List all MongoDB collections with document counts."""
    db = get_database()
    names = await db.list_collection_names()
    result = []
    for name in sorted(names):
        count = await db[name].count_documents({})
        result.append({"name": name, "count": count})
    return result


@router.get("/{collection}")
async def get_collection_docs(
    collection: str,
    limit: int = Query(default=20, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_curator),
) -> List[Dict[str, Any]]:
    """Sample documents from a collection."""
    db = get_database()
    names = await db.list_collection_names()
    if collection not in names:
        raise HTTPException(status_code=404, detail=f"Collection '{collection}' not found")
    docs = []
    async for doc in db[collection].find({}, limit=limit, skip=skip):
        docs.append(_serialize_doc(doc))
    return docs
