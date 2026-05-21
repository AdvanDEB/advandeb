"""
KB document metadata API — serves bibliographic data from the ArangoDB documents collection.

GET /api/kb/documents/{document_id}
    Returns the full document record (title, doi, authors, year, journal,
    abstract, keywords, etc.) for a given document key (hex ObjectId string).
    Used by the frontend NodeInspector when a document graph node is clicked.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.core.database import get_arango_db

router = APIRouter()
logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kb-doc-route")


@router.get("/{document_id}")
async def get_kb_document(
    document_id: str,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Return bibliographic metadata for a KB document by its key.

    Fields returned (when populated):
      title, doi, authors, year, journal, abstract, keywords,
      source_type, source_path, general_domain, processing_status,
      references, created_at, updated_at.
    """
    arango = get_arango_db()

    def _fetch():
        return arango.get("documents", document_id)

    loop = asyncio.get_running_loop()
    doc = await loop.run_in_executor(_executor, _fetch)

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Clean up internal ArangoDB fields
    doc.pop("_rev", None)
    doc.pop("_id", None)
    # Expose _key as id for frontend compatibility
    doc["id"] = doc.pop("_key", document_id)

    return doc
