"""
Workshop wiki: the cleaned, bilingual notes from the AdvanDEB workshop
(the "2026Workshop" page).

Read-only, and only for the people who were there. Administrators always see
it; everyone else needs the ``workshop_2026`` capability, which an
administrator grants per user here (/access). New accounts start without it,
experts included. What each reader then sees inside the wiki depends on their
tier, which app.services.wiki_service filters for.

An external contributor is confined to the elicitation routes by app.core.auth,
except that the workshop grant also opens /api/wiki to them.
"""
from typing import List, Literal

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.auth import CAP_WORKSHOP_2026, ROLE_EXTERNAL_CONTRIBUTOR
from app.core.config import settings
from app.core.dependencies import CAP_SF_ELICITATION, require_admin, require_workshop
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
async def wiki_index(current_user: dict = Depends(require_workshop)):
    """Every note the caller may open: titles, sections, tags, badge counts."""
    return _call(_store().index, current_user)


@router.get("/notes/{note_id}")
async def wiki_note(note_id: str, current_user: dict = Depends(require_workshop)):
    """One note in both languages, with its links filtered to the caller's tier."""
    note = _call(_store().note, current_user, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


@router.get("/graph")
async def wiki_graph(current_user: dict = Depends(require_workshop)):
    return _call(_store().graph, current_user)


@router.get("/search")
async def wiki_search(
    q: str = Query(..., min_length=1, max_length=200),
    lang: Literal["hr", "en"] = "hr",
    limit: int = Query(40, ge=1, le=100),
    current_user: dict = Depends(require_workshop),
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


# --------------------------------------------------------------------------- #
# Who may open the wiki                                                         #
# --------------------------------------------------------------------------- #

def _is_expert(roles: list, caps: list) -> bool:
    """Someone who can give expert judgments (as /api/elicitation/experts)."""
    return ("knowledge_curator" in roles or ROLE_EXTERNAL_CONTRIBUTOR in roles
            or CAP_SF_ELICITATION in caps)


@router.get("/access")
async def list_access(current_user: dict = Depends(require_admin)):
    """Every account, whether it may open the wiki, and whether it is an expert.

    The admin page offers the experts without access as one batch to grant,
    so that the people who were at the workshop get in with one confirmation.
    """
    from app.core.database import get_database

    users = []
    async for u in get_database().users.find(
            {}, {"email": 1, "full_name": 1, "roles": 1, "capabilities": 1,
                 "status": 1, "created_at": 1}):
        roles = u.get("roles") or []
        caps = u.get("capabilities") or []
        admin = "administrator" in roles
        created = u.get("created_at")
        users.append({
            "id": str(u["_id"]),
            "name": u.get("full_name") or u.get("email"),
            "email": u.get("email"),
            "roles": roles,
            "status": u.get("status") or "active",
            "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
            "is_admin": admin,
            "is_expert": not admin and _is_expert(roles, caps),
            "granted": CAP_WORKSHOP_2026 in caps,
            "has_access": admin or CAP_WORKSHOP_2026 in caps,
        })
    users.sort(key=lambda u: (not u["has_access"], not u["is_expert"], (u["name"] or "").lower()))
    return {"users": users, "with_access": sum(1 for u in users if u["has_access"])}


class AccessChange(BaseModel):
    user_ids: List[str] = Field(..., min_length=1, max_length=500)
    granted: bool


@router.post("/access")
async def set_access(change: AccessChange, current_user: dict = Depends(require_admin)):
    """Grant or revoke the wiki for one account or a batch of them."""
    from app.core.database import get_database

    try:
        ids = [ObjectId(i) for i in change.user_ids]
    except (InvalidId, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid user id")
    op = ({"$addToSet": {"capabilities": CAP_WORKSHOP_2026}} if change.granted
          else {"$pull": {"capabilities": CAP_WORKSHOP_2026}})
    users = get_database().users
    matched = 0
    for oid in ids:
        res = await users.update_one({"_id": oid}, op)
        matched += res.matched_count
    if not matched:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return {"capability": CAP_WORKSHOP_2026, "granted": change.granted,
            "requested": len(ids), "matched": matched}
