"""
Human annotation API.

Replaces the former Scenarios section. Annotators work a fixed, seeded queue
of stylized facts; their decisions form the gold set that every machine
measurement in the consensus pipeline is scored against.

Access: knowledge curators and administrators. The `capabilities` field on the
user model exists but nothing grants or checks it yet
(docs/SYSTEM-OVERVIEW.md 6), so role is the honest gate for now; an
`sf_annotator` capability slots in here when capabilities are wired up.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import get_current_user
from app.core.dependencies import require_admin, require_curator
from app.models.annotation import (
    AnnotationDecision, AnnotationProgress, QueueItem,
)
from app.services.annotation_service import AnnotationService

router = APIRouter()


@router.get("/next", response_model=QueueItem | None)
async def next_item(current_user: dict = Depends(require_curator)):
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
    current_user: dict = Depends(require_curator),
):
    """Record one annotation decision."""
    service = AnnotationService()
    result = await service.submit(decision, current_user["id"])
    if result.get("status") == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=result.get("detail", "could not record"))
    return result


@router.get("/progress", response_model=AnnotationProgress)
async def progress(current_user: dict = Depends(require_curator)):
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
