"""
Document submission API routes.

User-submitted document suggestions live in the app MongoDB (advandeb.document_submissions).
KB-ingested documents live in ArangoDB — accessible via /api/kb/documents.

This router handles the suggestion lifecycle:
  POST   /api/documents/               — submit a document (metadata form)
  POST   /api/documents/upload         — submit a document (file upload)
  GET    /api/documents/               — list submissions (filter by status)
  GET    /api/documents/{id}           — get a single submission
  PATCH  /api/documents/{id}/approve   — curator approve/reject
  DELETE /api/documents/{id}           — delete a submission
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from typing import List, Optional
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.core.dependencies import require_curator
from app.models.user_submission import (
    DocumentSubmission,
    DocumentSubmissionCreate,
)
from app.services.user_submission_service import UserSubmissionService


router = APIRouter()


class DocumentApproveRequest(BaseModel):
    action: str  # "approve" | "reject"
    comment: Optional[str] = None


@router.post("/", response_model=DocumentSubmission)
async def create_document_submission(
    document: DocumentSubmissionCreate,
    current_user: dict = Depends(get_current_user),
):
    """Submit a document for curator review (metadata form)."""
    svc = UserSubmissionService()
    return await svc.create_document_submission(document, current_user["id"])


@router.post("/upload", response_model=DocumentSubmission)
async def upload_document_submission(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_curator),
):
    """Upload a document file directly into the corpus. Curator/admin only."""
    svc = UserSubmissionService()
    return await svc.upload_document_submission(file, current_user["id"])


@router.get("/", response_model=List[DocumentSubmission])
async def list_document_submissions(
    skip: int = 0,
    limit: int = 100,
    search: str = "",
    status: str = "",
    current_user: dict = Depends(get_current_user),
):
    """List document submissions. Curators filter by status='suggestion'."""
    svc = UserSubmissionService()
    return await svc.list_document_submissions(
        skip=skip, limit=limit, search=search, status=status
    )


@router.get("/{submission_id}", response_model=DocumentSubmission)
async def get_document_submission(
    submission_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get a document submission by ID."""
    svc = UserSubmissionService()
    submission = await svc.get_document_submission(submission_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )
    return submission


@router.patch("/{submission_id}/approve")
async def approve_document_submission(
    submission_id: str,
    body: DocumentApproveRequest,
    current_user: dict = Depends(require_curator),
):
    """Curator approves or rejects a document submission.

    approve → queues the document for KB ingestion pipeline.
    reject  → marks it as rejected.
    """
    if body.action not in ("approve", "reject"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="action must be 'approve' or 'reject'",
        )
    svc = UserSubmissionService()
    result = await svc.approve_document_submission(
        submission_id,
        reviewer_id=current_user["id"],
        action=body.action,
        comment=body.comment,
    )
    if not result.get("updated"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.get("error", "Submission not found"),
        )
    return result


@router.delete("/{submission_id}")
async def delete_document_submission(
    submission_id: str,
    current_user: dict = Depends(require_curator),
):
    """Delete a document submission."""
    svc = UserSubmissionService()
    await svc.delete_document_submission(submission_id)
    return {"message": "Submission deleted"}
