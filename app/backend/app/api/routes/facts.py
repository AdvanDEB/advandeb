"""
Fact and stylized fact submission API routes.

User-submitted fact/SF suggestions live in app MongoDB
(advandeb.fact_submissions, advandeb.sf_submissions).
KB-canonical facts and SFs live in ArangoDB.

Routes:
  POST   /api/facts/                     — submit a fact
  GET    /api/facts/                     — list fact submissions
  GET    /api/facts/{id}                 — get a fact submission
  PATCH  /api/facts/{id}/review          — curator review (publish/reject)

  POST   /api/facts/stylized             — submit a stylized fact
  GET    /api/facts/stylized/            — list SF submissions
  PATCH  /api/facts/stylized/{id}/review — curator review
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.core.dependencies import require_curator
from app.models.user_submission import (
    FactSubmission,
    FactSubmissionCreate,
    StylizedFactSubmission,
    StylizedFactSubmissionCreate,
)
from app.services.user_submission_service import UserSubmissionService


router = APIRouter()


class FactReviewRequest(BaseModel):
    status: str  # "published" | "rejected" | "pending_review"
    review_comment: Optional[str] = None


class StylizedFactReviewRequest(BaseModel):
    status: str  # "published" | "rejected"
    review_comment: Optional[str] = None


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

@router.post("/", response_model=FactSubmission)
async def create_fact_submission(
    fact: FactSubmissionCreate,
    current_user: dict = Depends(get_current_user),
):
    """Submit a fact for curator review."""
    svc = UserSubmissionService()
    return await svc.create_fact_submission(fact, current_user["id"])


@router.get("/", response_model=List[FactSubmission])
async def list_fact_submissions(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """List fact submissions."""
    svc = UserSubmissionService()
    return await svc.list_fact_submissions(
        skip=skip, limit=limit, status_filter=status_filter
    )


@router.get("/{fact_id}", response_model=FactSubmission)
async def get_fact_submission(
    fact_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get a fact submission by ID."""
    svc = UserSubmissionService()
    fact = await svc.get_fact_submission(fact_id)
    if not fact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Fact submission not found"
        )
    return fact


@router.patch("/{fact_id}/review")
async def review_fact_submission(
    fact_id: str,
    body: FactReviewRequest,
    current_user: dict = Depends(require_curator),
):
    """Curator publishes or rejects a fact submission."""
    allowed = {"published", "rejected", "pending_review"}
    if body.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {', '.join(sorted(allowed))}",
        )
    svc = UserSubmissionService()
    result = await svc.approve_fact_submission(
        fact_id,
        reviewer_id=current_user["id"],
        new_status=body.status,
        review_comment=body.review_comment,
    )
    if not result.get("updated"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.get("error", "Fact submission not found"),
        )
    return result


# ---------------------------------------------------------------------------
# Stylized facts
# ---------------------------------------------------------------------------

@router.post("/stylized", response_model=StylizedFactSubmission)
async def create_sf_submission(
    stylized_fact: StylizedFactSubmissionCreate,
    current_user: dict = Depends(get_current_user),
):
    """Submit a stylized fact for curator review."""
    svc = UserSubmissionService()
    return await svc.create_sf_submission(stylized_fact, current_user["id"])


@router.get("/stylized/", response_model=List[StylizedFactSubmission])
async def list_sf_submissions(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """List stylized fact submissions."""
    svc = UserSubmissionService()
    return await svc.list_sf_submissions(
        skip=skip, limit=limit, status_filter=status_filter
    )


@router.patch("/stylized/{sf_id}/review")
async def review_sf_submission(
    sf_id: str,
    body: StylizedFactReviewRequest,
    current_user: dict = Depends(require_curator),
):
    """Curator publishes or rejects a stylized fact submission."""
    allowed = {"published", "rejected"}
    if body.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {', '.join(sorted(allowed))}",
        )
    svc = UserSubmissionService()
    result = await svc.approve_sf_submission(
        sf_id,
        reviewer_id=current_user["id"],
        new_status=body.status,
        review_comment=body.review_comment,
    )
    if not result.get("updated"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.get("error", "Stylized fact submission not found"),
        )
    return result
