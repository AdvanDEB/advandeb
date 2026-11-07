"""
Workshop wiki: the cleaned, bilingual notes from the AdvanDEB workshop.

Read-only and for signed-in members. What each caller sees depends on their
tier, and app.services.wiki_service filters for it. External contributors never
reach these routes, because app.core.auth confines them to their own prefixes.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.dependencies import require_admin
from app.services.wiki_service import WikiStore, WikiUnavailable, get_wiki_store

router = APIRouter()

UNAVAILABLE = "The workshop wiki has not been published on this server yet."


def _store() -> WikiStore:
    return get_wiki_store(settings.WIKI_BUNDLE_PATH)


def _call(fn, *args):
    try:
        return fn(*args)
    except WikiUnavailable:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=UNAVAILABLE)


@router.get("/index")
async def wiki_index(current_user: dict = Depends(get_current_user)):
    """Every note the caller may open: titles, sections, tags, badge counts."""
    return _call(_store().index, current_user)


@router.get("/notes/{note_id}")
async def wiki_note(note_id: str, current_user: dict = Depends(get_current_user)):
    """One note in both languages, with its links filtered to the caller's tier."""
    note = _call(_store().note, current_user, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


@router.get("/graph")
async def wiki_graph(current_user: dict = Depends(get_current_user)):
    return _call(_store().graph, current_user)


@router.get("/search")
async def wiki_search(
    q: str = Query(..., min_length=1, max_length=200),
    lang: Literal["hr", "en"] = "hr",
    limit: int = Query(40, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    return {"results": _call(_store().search, current_user, q, lang, limit)}


@router.post("/reload")
async def wiki_reload(current_user: dict = Depends(require_admin)):
    """Re-read the bundle now. A replaced file is picked up on the next request
    anyway; this makes it explicit and reports what was loaded."""
    store = _store()
    store._mtime = None
    bundle = _call(store.bundle)
    return {"built": bundle.get("built"), "notes": len(bundle["notes"])}
