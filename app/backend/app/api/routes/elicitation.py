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
from app.core.dependencies import (
    is_curator, require_admin, require_curator, require_elicitor,
)
from app.models.elicitation import (
    ExpertReferenceCreate,
    CalibrationDecision, CalibrationFeedback, CalibrationItem,
    CalibrationSet, CalibrationSetDraft, CalibrationSetList,
    AdminStats, CalibrationStatus, CandidateReview, CandidateReviewResult,
    DecisionReceipt, ElicitationDecision, ElicitationEvent,
    ElicitationProgress, EventReceipt, EvidenceCandidateList,
    EvidenceSetDetail, EvidenceSetOptionList, ExpertList, Guidelines,
    HistoryResponse, QueueItem,
)
from app.services.elicitation_service import ElicitationService
from app.services.expert_reference_service import ExpertReferenceService

router = APIRouter()


def _raise_on_error(result: dict, default_code: int = 400) -> dict:
    """Map a service error to its HTTP status; pass a success through."""
    if result.get("status") == "error":
        raise HTTPException(status_code=int(result.get("code") or default_code),
                            detail=result.get("detail", "could not record"))
    return result


# What the machine panel concluded about a paper. Shown to an expert while
# they judge, it is the machine assessment by another route — an anchor in the
# very judgment being measured — so only curators receive it.
_MACHINE_FIELDS = ("panel_labels", "agrees_with_panel")


def _for_expert(ref: dict) -> dict:
    res = dict(ref.get("resolution") or {})
    for k in _MACHINE_FIELDS:
        res.pop(k, None)
    return {**ref, "resolution": res}


def _refusal(result: dict) -> dict:
    """A refused rebuild is an error to the caller, not a quiet status."""
    if result.get("status") == "refused":
        return {"status": "error", "code": status.HTTP_409_CONFLICT,
                "detail": result.get("detail")}
    return result


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


@router.post("/decide", response_model=DecisionReceipt)
async def submit_decision(
    decision: ElicitationDecision,
    current_user: dict = Depends(require_elicitor),
):
    """Record one elicitation decision — on the item /next serves, only.

    400 the payload does not answer its task · 403 conflict of interest or
    calibration incomplete · 404 not a queue item · 409 not the head of this
    expert's queue (already judged, panel requirement met, or never served).
    """
    service = ElicitationService()
    return _raise_on_error(await service.submit(decision, current_user["id"]))


@router.post("/events", response_model=EventReceipt)
async def log_event(
    event: ElicitationEvent,
    current_user: dict = Depends(require_elicitor),
):
    """Log an interface event — so far, opening or closing the machine
    assessment. Exposure is derived from these at submit time, so anchoring is
    measured rather than inferred from the panel's state at the last moment."""
    return _raise_on_error(
        await ElicitationService().log_event(event, current_user["id"]))


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
    """Generate the fixed fact-level order for the current collection version.

    The fact-level tasks are not served (SERVED_TASKS); the block is kept so
    that decision can be reversed. Idempotent, and refuses to rebuild once
    elicitation has begun unless forced: reshuffling would silently change
    what the completed prefix represents.
    """
    service = ElicitationService()
    return _raise_on_error(_refusal(await service.build_queue(force=force)))


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
    return _raise_on_error(
        _refusal(await ElicitationService().build_evidence_queue(force=force)))


@router.get("/experts", response_model=ExpertList)
async def list_experts(current_user: dict = Depends(require_admin)):
    """Who currently holds the elicitation capability, and who could — with
    their tier, how much they have judged, and which author slugs they answer
    to (the conflict-of-interest link)."""
    from app.core.database import get_database
    from app.core.dependencies import CAP_SF_ELICITATION, ROLE_EXTERNAL_CONTRIBUTOR

    db = get_database()
    counts = {}
    async for row in db.elicitations.aggregate(
            [{"$group": {"_id": "$expert_id", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    out = []
    async for u in db.users.find({}, {"email": 1, "full_name": 1, "roles": 1,
                                      "capabilities": 1, "tier": 1,
                                      "author_slugs": 1}):
        roles = u.get("roles") or []
        caps = u.get("capabilities") or []
        uid = str(u["_id"])
        out.append({
            "id": uid,
            "name": u.get("full_name") or u.get("email"),
            "roles": roles,
            "tier": u.get("tier"),
            # Mirrors require_elicitor: an external contributor reaches the
            # elicitation routes by role alone.
            "can_elicit": ("administrator" in roles
                           or "knowledge_curator" in roles
                           or ROLE_EXTERNAL_CONTRIBUTOR in roles
                           or CAP_SF_ELICITATION in caps),
            "has_capability": CAP_SF_ELICITATION in caps,
            "n_elicitations": counts.get(uid, 0),
            "author_slugs": u.get("author_slugs") or [],
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
    """The next case of the published calibration set, or null once this
    expert has worked them all (or none is published).

    Served like a real evidence item — passages, citations and the same form —
    because calibration trains the act the queue asks for.
    """
    return await ElicitationService().calibration_next(current_user["id"])


@router.post("/calibration/decide", response_model=CalibrationFeedback)
async def calibration_decide(
    decision: CalibrationDecision,
    current_user: dict = Depends(require_elicitor),
):
    """Answer one calibration case and see the team's reference answer and
    explanation at once.

    Calibration teaches, so nothing is withheld. The result is stored as a
    quality signal, never as an automatic exclusion gate.
    """
    result = await ElicitationService().calibration_submit(
        decision, current_user["id"])
    return _raise_on_error(result)


@router.get("/calibration/status", response_model=CalibrationStatus)
async def calibration_status(current_user: dict = Depends(require_elicitor)):
    """Where this expert stands against the published calibration set.

    `required` is what the client gates on, and what the server gates /next
    and /decide on. It is false while no set is published: experts are never
    held up by a set the team has not chosen yet.
    """
    return await ElicitationService().calibration_status(current_user["id"])


@router.get("/calibration/sets", response_model=CalibrationSetList)
async def calibration_sets(current_user: dict = Depends(require_admin)):
    """Every calibration set version, newest first, and which is published."""
    return await ElicitationService().list_calibration_sets()


@router.get("/calibration/evidence-sets", response_model=EvidenceSetOptionList)
async def calibration_evidence_sets(current_user: dict = Depends(require_admin)):
    """The evidence sets a calibration item can be built from."""
    return await ElicitationService().evidence_set_options()


@router.get("/calibration/evidence-sets/{evidence_set_id}",
            response_model=EvidenceSetDetail)
async def calibration_evidence_set(
    evidence_set_id: str,
    current_user: dict = Depends(require_admin),
):
    """One evidence set with its passages as an expert sees them."""
    detail = await ElicitationService().evidence_set_detail(evidence_set_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="no such evidence set")
    return detail


@router.post("/calibration/sets", response_model=CalibrationSet)
async def create_calibration_set(
    draft: CalibrationSetDraft,
    current_user: dict = Depends(require_admin),
):
    """Save a new draft version: the items the team picked, each with its
    agreed reference answer and explanation."""
    return _raise_on_error(await ElicitationService().save_calibration_draft(
        draft, current_user["id"]))


@router.put("/calibration/sets/{version}", response_model=CalibrationSet)
async def update_calibration_set(
    version: int,
    draft: CalibrationSetDraft,
    current_user: dict = Depends(require_admin),
):
    """Replace a draft's items. Published and retired versions are not
    edited — a change to the instrument is a new version."""
    return _raise_on_error(await ElicitationService().save_calibration_draft(
        draft, current_user["id"], version=version))


@router.post("/calibration/sets/{version}/publish", response_model=CalibrationSet)
async def publish_calibration_set(
    version: int,
    current_user: dict = Depends(require_admin),
):
    """Publish a draft, retiring the previous published set. From then on
    each expert works it once before their next item, and its facts leave
    the measured queue."""
    return _raise_on_error(
        await ElicitationService().publish_calibration_set(version))


@router.delete("/calibration/sets/{version}")
async def delete_calibration_set(
    version: int,
    current_user: dict = Depends(require_admin),
):
    """Delete a draft. Published and retired versions are kept: judgments
    are stamped with them."""
    return _raise_on_error(
        await ElicitationService().delete_calibration_draft(version))


@router.get("/stats/admin", response_model=AdminStats)
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
    if not is_curator(current_user) and result.get("reference"):
        result = {**result, "reference": _for_expert(result["reference"])}
    return result


@router.get("/references")
async def list_references(
    sf_number: int,
    mine_only: bool = True,
    current_user: dict = Depends(require_elicitor),
):
    """References for a fact — the expert's own.

    Other experts' references are for curators only. An expert who could
    read that a colleague cited a paper as opposing a fact would be judging
    with the colleague's answer in view, which is the independence the
    agreement statistics rest on.
    """
    if not mine_only and not is_curator(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="only curators see other experts' references")
    svc = ExpertReferenceService()
    refs = await svc.list_for(sf_number,
                              current_user["id"] if mine_only else None)
    if not is_curator(current_user):
        # Neither what the machine made of a paper nor what other experts
        # asserted about this fact: both are other judges' answers.
        return {"references": [_for_expert(r) for r in refs],
                "asserted_evidence": None}
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


@router.get("/references/candidates", response_model=EvidenceCandidateList)
async def reference_candidates(
    status_filter: str = "pending",
    limit: int = 200,
    current_user: dict = Depends(require_curator),
):
    """Expert-named papers as evidence candidates, for curator review.

    `status_filter` is pending, accepted or rejected.
    """
    if status_filter not in ("pending", "accepted", "rejected"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="status_filter is pending, accepted or rejected")
    return await ExpertReferenceService().candidates(status_filter, limit)


@router.post("/references/{reference_id}/review",
             response_model=CandidateReviewResult)
async def review_reference(
    reference_id: str,
    review: CandidateReview,
    current_user: dict = Depends(require_curator),
):
    """Accept or reject an expert-named paper as evidence for its fact."""
    return _raise_on_error(await ExpertReferenceService().review(
        reference_id, current_user["id"], review.accept, review.comment))
