"""
Enrolment API — becoming an elicitation participant.

Self-signup with administrator approval (advandeb_methods docs/10 section 5).
The public endpoint records a request and nothing more: no account exists, and
nothing is granted, until an administrator assigns a tier.

Tier assignment is the scientific decision the approval step exists for. Who
counts as a panel member determines what the agreement statistics are agreement
*over*, so it is never inferred from the form.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.dependencies import require_admin
from app.core.limiter import limiter
from app.models.enrolment import (
    EnrolmentDecision, EnrolmentDecisionResult, EnrolmentRequest,
    EnrolmentRequestList, EnrolmentSubmitted,
)
from app.services.enrolment_service import EnrolmentService

router = APIRouter()


@router.post("/request", response_model=EnrolmentSubmitted)
@limiter.limit("5/minute")
async def submit_request(request: Request, body: EnrolmentRequest):
    """Request access. Public, rate-limited.

    Returns the same response whether or not the email is already known, so it
    cannot be used to enumerate who is already enrolled.
    """
    return await EnrolmentService().submit_request(body)


@router.get("/requests", response_model=EnrolmentRequestList)
async def list_requests(
    status_filter: str | None = None,
    current_user: dict = Depends(require_admin),
):
    """Pending and decided requests, with any authorship conflict surfaced.

    The conflict is shown at the moment of the decision rather than discovered
    later: several likely contributors authored stylized facts.
    """
    return {"requests": await EnrolmentService().list_requests(status_filter)}


@router.post("/requests/{request_id}/decide",
             response_model=EnrolmentDecisionResult)
async def decide_request(
    request_id: str,
    decision: EnrolmentDecision,
    current_user: dict = Depends(require_admin),
):
    """Approve at a tier, or decline. The account is created on approval."""
    result = await EnrolmentService().decide(
        request_id, decision, current_user["id"])
    if result.get("status") == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=result.get("detail", "could not decide"))
    return result
