"""
KB document metadata API — ArangoDB corpus documents.

GET    /api/kb/documents/              — list corpus with search/filter
GET    /api/kb/documents/{id}          — single document metadata
POST   /api/kb/documents/{id}/flag     — flag as potentially irrelevant (any user)
DELETE /api/kb/documents/{id}/flag     — remove flag (curator only)
DELETE /api/kb/documents/{id}          — delete (curator only; blocked if completed)
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.core.database import get_arango_db
from app.core.dependencies import require_curator

router = APIRouter()
logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="kb-doc-route")


_HTML_TAG_RE = __import__("re").compile(r"<[^>]+>")


def _strip_html(value: Any) -> Any:
    """Strip HTML tags from a string field (titles sometimes contain <i> etc.)."""
    if isinstance(value, str):
        return _HTML_TAG_RE.sub("", value)
    return value


@router.get("")
@router.get("/")
async def list_kb_documents(
    search: str = "",
    status: str = "",
    source_type: str = "",
    flagged: str = "",
    include_web: bool = False,
    limit: int = 50,
    skip: int = 0,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """List KB corpus documents with pagination.

    Returns {items, total, skip, limit}.
    Default: queries document_meta (pipeline docs only — fast even at 100M scale).
    include_web=true or source_type='web': falls back to the full documents collection.
    """
    arango = get_arango_db()

    # Use the fast document_meta table unless the caller wants web abstracts.
    use_web = include_web or source_type == "web"
    collection = "documents" if use_web else "document_meta"

    filters: List[str] = []
    bind_vars: Dict[str, Any] = {"skip": skip, "limit": limit}

    # When querying the full documents collection we must restrict to web records
    # (the pipeline docs are already in document_meta, no point showing them twice).
    if use_web:
        if source_type == "web":
            filters.append("doc.source_type == 'web'")
        else:
            # include_web=true but no specific type → show web records only
            # (pipeline records are shown in the default view)
            filters.append("doc.source_type == 'web'")
    elif source_type:
        # Filter within document_meta by a specific pipeline type
        filters.append("doc.source_type == @source_type")
        bind_vars["source_type"] = source_type

    if search:
        filters.append(
            "(CONTAINS(LOWER(doc.title), LOWER(@search))"
            " OR CONTAINS(LOWER(doc.doi), LOWER(@search))"
            " OR CONTAINS(LOWER(doc.journal), LOWER(@search)))"
        )
        bind_vars["search"] = search

    if status:
        filters.append("doc.processing_status == @status")
        bind_vars["status"] = status

    if flagged == "true":
        filters.append("doc.potentially_irrelevant == true")
    elif flagged == "false":
        filters.append("(doc.potentially_irrelevant == false OR doc.potentially_irrelevant == null)")

    where = "\n".join(f"  FILTER {f}" for f in filters)

    aql_items = f"""
    FOR doc IN {collection}
      {where}
      SORT doc._key DESC
      LIMIT @skip, @limit
      RETURN {{
        id: doc._key,
        title: doc.title,
        doi: doc.doi,
        authors: doc.authors,
        year: doc.year,
        journal: doc.journal,
        abstract: doc.abstract,
        source_type: doc.source_type,
        processing_status: doc.processing_status,
        num_chunks: doc.num_chunks,
        num_facts: doc.num_facts,
        general_domain: doc.general_domain,
        potentially_irrelevant: doc.potentially_irrelevant,
        flag_reason: doc.flag_reason,
        flagged_at: doc.flagged_at,
        created_at: doc.created_at
      }}
    """

    aql_count = f"""
    RETURN LENGTH(
      FOR doc IN {collection}
        {where}
        RETURN 1
    )
    """

    def _fetch():
        items = arango.aql(aql_items, bind_vars)
        for d in items:
            d["title"] = _strip_html(d.get("title") or "")
            d["journal"] = _strip_html(d.get("journal") or "")
        count_bind = {k: v for k, v in bind_vars.items() if k not in ("skip", "limit")}
        total_result = arango.aql(aql_count, count_bind)
        total = total_result[0] if total_result else 0
        return {"items": items, "total": total, "skip": skip, "limit": limit}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _fetch)


@router.get("/{document_id}")
async def get_kb_document(
    document_id: str,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return full bibliographic metadata for a KB document."""
    arango = get_arango_db()

    def _fetch():
        return arango.get("documents", document_id)

    loop = asyncio.get_running_loop()
    doc = await loop.run_in_executor(_executor, _fetch)

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.pop("_rev", None)
    doc.pop("_id", None)
    doc["id"] = doc.pop("_key", document_id)
    return doc


class FlagRequest(BaseModel):
    reason: str = ""


@router.post("/{document_id}/flag")
async def flag_kb_document(
    document_id: str,
    body: FlagRequest,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Flag a document as potentially irrelevant. Any authenticated user."""
    arango = get_arango_db()

    def _flag():
        doc = arango.get("documents", document_id)
        if doc is None:
            return None
        patch = {
            "_key": document_id,
            "potentially_irrelevant": True,
            "flag_reason": body.reason,
            "flagged_by": current_user["id"],
            "flagged_at": datetime.now(timezone.utc).isoformat(),
        }
        arango.db.collection("documents").update(patch)
        try:
            arango.db.collection("document_meta").update(patch)
        except Exception:
            pass
        return {"flagged": True}

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_executor, _flag)
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@router.delete("/{document_id}/flag")
async def unflag_kb_document(
    document_id: str,
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    """Remove the potentially-irrelevant flag. Curator only."""
    arango = get_arango_db()

    def _unflag():
        doc = arango.get("documents", document_id)
        if doc is None:
            return None
        patch = {
            "_key": document_id,
            "potentially_irrelevant": False,
            "flag_reason": None,
            "flagged_by": None,
            "flagged_at": None,
        }
        arango.db.collection("documents").update(patch)
        try:
            arango.db.collection("document_meta").update(patch)
        except Exception:
            pass
        return {"unflagged": True}

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_executor, _unflag)
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@router.delete("/{document_id}")
async def delete_kb_document(
    document_id: str,
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    """Delete a document from the corpus.

    Blocked when processing_status is 'completed' — those documents have
    chunks, facts and graph edges that depend on them. Flag them as
    potentially irrelevant instead.
    """
    arango = get_arango_db()

    def _delete():
        doc = arango.get("documents", document_id)
        if doc is None:
            return "not_found"
        if doc.get("processing_status") == "completed":
            return "blocked"
        # Remove any partial chunks that may exist for non-completed docs
        try:
            arango.aql(
                "FOR c IN chunks FILTER c.document_id == @key REMOVE c IN chunks",
                {"key": document_id},
            )
        except Exception:
            pass
        arango.delete("documents", document_id)
        try:
            arango.delete("document_meta", document_id)
        except Exception:
            pass
        return "deleted"

    loop = asyncio.get_running_loop()
    outcome = await loop.run_in_executor(_executor, _delete)

    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="Document not found")
    if outcome == "blocked":
        raise HTTPException(
            status_code=409,
            detail=(
                "This document is incorporated into the knowledge base and cannot be deleted. "
                "Use 'Flag as irrelevant' instead."
            ),
        )
    return {"deleted": document_id}
