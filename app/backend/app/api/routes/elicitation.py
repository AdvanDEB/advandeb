"""
Expert elicitation API.

Replaces the former Scenarios section. Experts work a fixed, seeded queue of
stylized facts; their judgments are one of the two consensus processes the
method compares — not a gold standard the machine is scored against, but a
second measurement of the same thing (advandeb_methods docs/09 section 0).

Access: the `sf_elicitation` capability, or a curator/administrator role.

Gating on the curator role alone would have been wrong and was caught by
looking at the actual user list: six of the eight potential experts - the DEB
authorities the comparison depends on - hold `knowledge_explorator` only. The
capability is granted per user by an administrator.
"""
from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.core.auth import get_current_user
from app.core.dependencies import require_admin, require_elicitor
from app.models.elicitation import (
    ExpertReferenceCreate,
    CalibrationDecision, CalibrationFeedback, CalibrationItem,
    ElicitationDecision, ElicitationProgress, Guidelines, HistoryResponse,
    QueueItem,
)
from app.services.elicitation_service import ElicitationService
from app.services.expert_reference_service import ExpertReferenceService

router = APIRouter()


@router.get("/next", response_model=QueueItem | None)
async def next_item(current_user: dict = Depends(require_elicitor)):
    """The next item this expert may work on.

    There is deliberately no endpoint to choose an item. Experts draw strictly
    from the head of a fixed order, because self-selection is what turns a
    stratified sample into a convenience sample — and the whole design rests on
    any prefix of the queue remaining a valid sample
    (advandeb_methods docs/02 4.1).
    """
    service = ElicitationService()
    return await service.next_item(current_user["id"])


@router.post("/decide")
async def submit_decision(
    decision: ElicitationDecision,
    current_user: dict = Depends(require_elicitor),
):
    """Record one elicitation decision."""
    service = ElicitationService()
    result = await service.submit(decision, current_user["id"])
    if result.get("status") == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=result.get("detail", "could not record"))
    return result


@router.get("/progress", response_model=ElicitationProgress)
async def progress(current_user: dict = Depends(require_elicitor)):
    """Queue progress, per-stratum counts, and which claims the elicitation so
    far actually supports (the claims ladder)."""
    service = ElicitationService()
    return await service.progress(current_user["id"])


@router.post("/queue/build")
async def build_queue(
    force: bool = False,
    current_user: dict = Depends(require_admin),
):
    """Generate the fixed elicitation order for the current collection version.

    Idempotent, and refuses to rebuild once elicitation has begun unless forced:
    reshuffling would silently change what the completed prefix represents.
    """
    service = ElicitationService()
    return await service.build_queue(force=force)


@router.post("/evidence/import")
async def import_evidence_sets(
    payload: dict = Body(...),
    force: bool = False,
    current_user: dict = Depends(require_admin),
):
    """Load the frozen evidence sets the agent panel read.

    The body is the verified export from advandeb_methods
    (`data/evidence/evidence_sets_v1.0.json`), whose content hashes were
    checked against the backfill manifest at export time.
    """
    return await ElicitationService().import_evidence_sets(payload, force=force)


@router.post("/queue/build-evidence")
async def build_evidence_queue(
    force: bool = False,
    current_user: dict = Depends(require_admin),
):
    """Queue the evidence-scoring items, ahead of the fact-level tasks.

    Evidence leads because the human ceiling is the measurement everything
    downstream is blocked on, and expert time is the project's scarcest input.
    """
    return await ElicitationService().build_evidence_queue(force=force)


@router.get("/experts")
async def list_experts(current_user: dict = Depends(require_admin)):
    """Who currently holds the elicitation capability, and who could."""
    from app.core.database import get_database
    from app.core.dependencies import CAP_SF_ELICITATION

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
            "can_elicit": ("administrator" in roles
                           or "knowledge_curator" in roles
                           or CAP_SF_ELICITATION in caps),
            "has_capability": CAP_SF_ELICITATION in caps,
        })
    return {"users": out,
            "eligible": sum(1 for u in out if u["can_elicit"])}


@router.post("/experts/{user_id}")
async def set_expert(
    user_id: str,
    granted: bool = True,
    current_user: dict = Depends(require_admin),
):
    """Grant or revoke the `sf_elicitation` capability.

    This is the first thing in the app to grant a capability at all — the field
    has existed since the beginning with nothing writing to it.
    """
    from bson import ObjectId
    from bson.errors import InvalidId

    from app.core.database import get_database
    from app.core.dependencies import CAP_SF_ELICITATION

    try:
        oid = ObjectId(user_id)
    except InvalidId:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="invalid user id")
    op = {"$addToSet": {"capabilities": CAP_SF_ELICITATION}} if granted \
        else {"$pull": {"capabilities": CAP_SF_ELICITATION}}
    res = await get_database().users.update_one({"_id": oid}, op)
    if not res.matched_count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="user not found")
    return {"user_id": user_id, "capability": CAP_SF_ELICITATION,
            "granted": granted}


@router.get("/history", response_model=HistoryResponse)
async def history(limit: int = 50,
                  current_user: dict = Depends(require_elicitor)):
    """This expert's own past judgments, newest first.

    Visible only to the person who made them. Seeing a colleague's answer
    before your own would destroy the independence the agreement statistics
    rest on.
    """
    service = ElicitationService()
    return {"items": await service.history(current_user["id"], limit)}


@router.get("/guidelines", response_model=Guidelines)
async def guidelines(current_user: dict = Depends(require_elicitor)):
    """Task definitions and option hints, served rather than duplicated in the
    client, and versioned so a mid-study change is auditable."""
    return ElicitationService().guidelines()


@router.get("/calibration/next", response_model=CalibrationItem | None)
async def calibration_next(current_user: dict = Depends(require_elicitor)):
    """The next calibration case, or null once the set is complete.

    Every expert works the fixed set before their judgments enter either
    stratum: it trains them, and their performance is a quality signal
    available before any real queue item is consumed.
    """
    return await ElicitationService().calibration_next(current_user["id"])


@router.post("/calibration/decide", response_model=CalibrationFeedback)
async def calibration_decide(
    decision: CalibrationDecision,
    current_user: dict = Depends(require_elicitor),
):
    """Answer one calibration case and see the documented reference at once.

    Calibration teaches, so nothing is withheld. The result is stored as a
    quality signal, never as an automatic exclusion gate.
    """
    result = await ElicitationService().calibration_submit(
        decision, current_user["id"])
    if result.get("status") == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=result.get("detail", "could not record"))
    return result


@router.get("/calibration/status")
async def calibration_status(current_user: dict = Depends(require_elicitor)):
    """How far through the calibration set this expert is."""
    return await ElicitationService().calibration_status(current_user["id"])


@router.post("/calibration/seed")
async def calibration_seed(force: bool = False,
                           current_user: dict = Depends(require_admin)):
    """Build the fixed calibration set from facts with documented provenance."""
    return await ElicitationService().seed_calibration(force=force)


@router.get("/stats/admin")
async def admin_stats(current_user: dict = Depends(require_admin)):
    """Where effort has gone, and what the panel still owes.

    `panel_coverage` counts positions whose `n_required` is met **by
    panel-tier judgments**. A dashboard counting all judgments would show
    healthy progress while the panel consensus went uncollected.
    """
    return await ElicitationService().admin_stats()


# --------------------------------------------------------------------------- #
# Expert-asserted evidence — the third instrument                              #
# --------------------------------------------------------------------------- #

@router.post("/references")
async def add_reference(
    ref: ExpertReferenceCreate,
    current_user: dict = Depends(require_elicitor),
):
    """Cite a publication by DOI as supporting or opposing a fact.

    Never moves the machine's score. A paper the corpus lacks is queued for
    ingestion, so the panel may change its mind — but only by reading it
    (advandeb_methods docs/09 section 2.5).
    """
    svc = ExpertReferenceService()
    tier = await ElicitationService().tier_of(current_user["id"])
    result = await svc.add(ref, current_user["id"], tier)
    if result.get("status") == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=result.get("detail", "could not record"))
    return result


@router.get("/references")
async def list_references(
    sf_number: int,
    mine_only: bool = True,
    current_user: dict = Depends(require_elicitor),
):
    """References for a fact — the expert's own by default."""
    svc = ExpertReferenceService()
    refs = await svc.list_for(sf_number,
                              current_user["id"] if mine_only else None)
    return {"references": refs,
            "asserted_evidence": await svc.asserted_evidence(sf_number)}


@router.delete("/references/{reference_id}")
async def delete_reference(
    reference_id: str,
    current_user: dict = Depends(require_elicitor),
):
    """Remove a reference. Own only, unless administrator."""
    svc = ExpertReferenceService()
    is_admin = "administrator" in (current_user.get("roles") or [])
    result = await svc.delete(reference_id, current_user["id"], is_admin)
    if result.get("status") == "error":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=result.get("detail", "not found"))
    return result


@router.get("/references/recall")
async def recall_summary(current_user: dict = Depends(require_admin)):
    """Retrieval-recall measurement from expert-named references.

    Every `in_corpus_not_retrieved` is a paper the corpus held and retrieval
    failed to surface, named by an expert who knew it was relevant — a figure
    the method has no other cheap source for (docs/09 section 2.5a).
    """
    return await ExpertReferenceService().recall_summary()
