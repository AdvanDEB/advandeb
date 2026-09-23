"""
Human annotation API.

Replaces the former Scenarios section. Annotators work a fixed, seeded queue
of stylized facts; their decisions form the gold set that every machine
measurement in the consensus pipeline is scored against.

Access: the `sf_annotator` capability, or a curator/administrator role.

Gating on the curator role alone would have been wrong and was caught by
looking at the actual user list: six of the eight potential annotators - the
DEB experts the gold set depends on - hold `knowledge_explorator` only. The
capability is granted per user by an administrator.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import get_current_user
from app.core.dependencies import require_admin, require_annotator
from app.models.annotation import (
    AnnotationDecision, AnnotationProgress, QueueItem,
)
from app.services.annotation_service import AnnotationService

router = APIRouter()


@router.get("/next", response_model=QueueItem | None)
async def next_item(current_user: dict = Depends(require_annotator)):
    """The next item this annotator may work on.

    There is deliberately no endpoint to choose an item. Annotators draw
    strictly from the head of a fixed order, because self-selection is what
    turns a stratified sample into a convenience sample — and the whole design
    rests on any prefix of the queue remaining a valid sample
    (advandeb_methods docs/02 4.1).
    """
    service = AnnotationService()
    return await service.next_item(current_user["id"])


@router.post("/decide")
async def submit_decision(
    decision: AnnotationDecision,
    current_user: dict = Depends(require_annotator),
):
    """Record one annotation decision."""
    service = AnnotationService()
    result = await service.submit(decision, current_user["id"])
    if result.get("status") == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=result.get("detail", "could not record"))
    return result


@router.get("/progress", response_model=AnnotationProgress)
async def progress(current_user: dict = Depends(require_annotator)):
    """Queue progress, per-stratum counts, and which claims the annotation so
    far actually supports (the claims ladder)."""
    service = AnnotationService()
    return await service.progress(current_user["id"])


@router.post("/queue/build")
async def build_queue(
    force: bool = False,
    current_user: dict = Depends(require_admin),
):
    """Generate the fixed annotation order for the current collection version.

    Idempotent, and refuses to rebuild once annotation has begun unless forced:
    reshuffling would silently change what the completed prefix represents.
    """
    service = AnnotationService()
    return await service.build_queue(force=force)


@router.get("/annotators")
async def list_annotators(current_user: dict = Depends(require_admin)):
    """Who currently holds the annotator capability, and who could."""
    from app.core.database import get_database
    from app.core.dependencies import CAP_SF_ANNOTATOR

    db = get_database()
    out = []
    async for u in db.users.find({}, {"email": 1, "full_name": 1, "roles": 1,
                                      "capabilities": 1}):
        roles = u.get("roles") or []
        caps = u.get("capabilities") or []
        out.append({
            "id": str(u["_id"]),
            "name": u.get("full_name") or u.get("email"),
            "roles": roles,
            "can_annotate": ("administrator" in roles
                             or "knowledge_curator" in roles
                             or CAP_SF_ANNOTATOR in caps),
            "has_capability": CAP_SF_ANNOTATOR in caps,
        })
    return {"users": out,
            "eligible": sum(1 for u in out if u["can_annotate"])}


@router.post("/annotators/{user_id}")
async def set_annotator(
    user_id: str,
    granted: bool = True,
    current_user: dict = Depends(require_admin),
):
    """Grant or revoke the `sf_annotator` capability.

    This is the first thing in the app to grant a capability at all — the field
    has existed since the beginning with nothing writing to it.
    """
    from bson import ObjectId
    from bson.errors import InvalidId

    from app.core.database import get_database
    from app.core.dependencies import CAP_SF_ANNOTATOR

    try:
        oid = ObjectId(user_id)
    except InvalidId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="invalid user id")
    op = {"$addToSet": {"capabilities": CAP_SF_ANNOTATOR}} if granted \
        else {"$pull": {"capabilities": CAP_SF_ANNOTATOR}}
    res = await get_database().users.update_one({"_id": oid}, op)
    if not res.matched_count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="user not found")
    return {"user_id": user_id, "capability": CAP_SF_ANNOTATOR,
            "granted": granted}
