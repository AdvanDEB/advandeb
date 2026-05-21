"""
User submission models — documents, facts, and stylized facts submitted by users
for curator review.

These live in the app MongoDB database (advandeb.user_submissions,
advandeb.fact_submissions, advandeb.sf_submissions) and are completely separate
from the KB ArangoDB data.  A curator approves a submission, which triggers
ingestion into the KB.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal
from datetime import datetime


# ---------------------------------------------------------------------------
# Document submissions
# ---------------------------------------------------------------------------

class DocumentSubmissionCreate(BaseModel):
    """Fields a user provides when submitting a document."""
    title: str
    source_type: str = "text"  # pdf, url, text
    url: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}


class DocumentSubmission(DocumentSubmissionCreate):
    """Document submission as stored in the database."""
    id: str = Field(alias="_id")
    uploader_id: str
    status: Literal["suggestion", "pending", "processing", "completed", "rejected"] = "suggestion"
    reviewer_id: Optional[str] = None
    review_comment: Optional[str] = None
    # Set once the submission has been ingested into the KB
    kb_document_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


# ---------------------------------------------------------------------------
# Fact submissions
# ---------------------------------------------------------------------------

class FactSubmissionCreate(BaseModel):
    """Fields a user provides when submitting a fact."""
    statement: str
    source_document_id: Optional[str] = None
    source_page: Optional[int] = None
    confidence: Optional[float] = None
    tags: list[str] = []
    metadata: Optional[Dict[str, Any]] = {}


class FactSubmission(FactSubmissionCreate):
    """Fact submission as stored in the database."""
    id: str = Field(alias="_id")
    creator_id: str
    status: Literal["suggestion", "pending_review", "published", "rejected"] = "suggestion"
    review_status: Optional[str] = None
    reviewer_id: Optional[str] = None
    review_comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


# ---------------------------------------------------------------------------
# Stylized fact submissions
# ---------------------------------------------------------------------------

class StylizedFactSubmissionCreate(BaseModel):
    """Fields a user provides when submitting a stylized fact."""
    summary: str = ""
    supporting_fact_ids: list[str] = []
    description: Optional[str] = None
    tags: list[str] = []


class StylizedFactSubmission(StylizedFactSubmissionCreate):
    """Stylized fact submission as stored in the database."""
    id: str = Field(alias="_id")
    creator_id: str
    status: Literal["suggestion", "published", "rejected"] = "suggestion"
    reviewer_id: Optional[str] = None
    review_comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True
