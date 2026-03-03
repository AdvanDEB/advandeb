from fastapi import APIRouter, HTTPException, Query
from typing import Any, Dict, List
from bson import ObjectId
from datetime import datetime

from advandeb_kb.database.mongodb import get_database

router = APIRouter()


@router.get("/collections")
async def list_collections() -> List[Dict[str, Any]]:
    """List all MongoDB collections with document counts."""
    db = await get_database()
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
) -> List[Dict[str, Any]]:
    """Sample documents from a collection."""
    db = await get_database()
    names = await db.list_collection_names()
    if collection not in names:
        raise HTTPException(status_code=404, detail=f"Collection '{collection}' not found")

    docs = []
    async for doc in db[collection].find({}, limit=limit, skip=skip):
        docs.append(_serialize_doc(doc))
    return docs


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
