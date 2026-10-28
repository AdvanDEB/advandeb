"""
User submission service — handles document, fact, and stylized fact suggestions
submitted by users for curator review.

All writes go to the app MongoDB database (advandeb), completely separate from
the KB ArangoDB.  Approving a document suggestion does not ingest it: a
suggestion carries no PDF (see approve_document_submission).
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

from app.core.database import get_database
from app.models.user_submission import (
    DocumentSubmission,
    DocumentSubmissionCreate,
    FactSubmission,
    FactSubmissionCreate,
    StylizedFactSubmission,
    StylizedFactSubmissionCreate,
)

logger = logging.getLogger(__name__)


class UserSubmissionService:
    """Service for user-submitted content pending curator review."""

    def __init__(self):
        db = get_database()
        self.doc_submissions = db.document_submissions
        self.fact_submissions = db.fact_submissions
        self.sf_submissions = db.sf_submissions

    # ------------------------------------------------------------------
    # Document submissions
    # ------------------------------------------------------------------

    async def create_document_submission(
        self,
        data: DocumentSubmissionCreate,
        uploader_id: str,
    ) -> DocumentSubmission:
        """Create a document submission from a metadata form."""
        doc = data.model_dump()
        doc.update(
            {
                "uploader_id": uploader_id,
                "status": "suggestion",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        result = await self.doc_submissions.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return DocumentSubmission(**doc)

    async def get_document_submission(self, submission_id: str) -> Optional[DocumentSubmission]:
        try:
            oid = ObjectId(submission_id)
        except (InvalidId, TypeError):
            return None
        doc = await self.doc_submissions.find_one({"_id": oid})
        if doc:
            doc["_id"] = str(doc["_id"])
            return DocumentSubmission(**doc)
        return None

    async def list_document_submissions(
        self,
        skip: int = 0,
        limit: int = 100,
        search: str = "",
        status: str = "",
        uploader_id: Optional[str] = None,
    ) -> List[DocumentSubmission]:
        """List document submissions with optional title search and status filter.

        ``search`` is matched literally (escaped), never as a pattern: a
        caller-supplied regex can be made to backtrack for minutes. Passing
        ``uploader_id`` restricts the list to that user's own submissions.
        """
        query: dict = {}
        if search:
            query["title"] = {"$regex": re.escape(search), "$options": "i"}
        if status:
            query["status"] = status
        if uploader_id is not None:
            query["uploader_id"] = uploader_id

        cursor = (
            self.doc_submissions.find(query)
            .skip(skip)
            .limit(limit)
            .sort("created_at", -1)
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(DocumentSubmission(**doc))
        return results

    async def approve_document_submission(
        self,
        submission_id: str,
        reviewer_id: str,
        action: str,  # "approve" | "reject"
        comment: Optional[str] = None,
    ) -> dict:
        """Reject a document submission, or refuse to approve it.

        reject  → marks status as 'rejected'.
        approve → 409, and the submission stays a suggestion. No suggestion has
                  a PDF the pipeline could read: the form takes metadata only,
                  and the retired upload route kept the extracted text but never
                  wrote the file. Approval used to queue a job for
                  ``uploads/<filename or title>`` anyway — a path nothing had
                  written — and launched it with ``asyncio.run`` in a thread,
                  against a Motor client bound to the server's own loop. The job
                  died on its first query, its batch stayed "running", and the
                  curator saw the suggestion disappear as if it had been queued.
        """
        try:
            oid = ObjectId(submission_id)
        except (InvalidId, TypeError):
            return {"updated": False, "error": "Submission not found"}

        doc = await self.doc_submissions.find_one({"_id": oid})
        if not doc:
            return {"updated": False, "error": "Submission not found"}

        if action == "approve":
            if doc.get("source_type") == "upload":
                reason = (
                    "The PDF uploaded with this suggestion was never stored, "
                    "only its extracted text, so there is nothing to ingest."
                )
            else:
                reason = (
                    "This suggestion has metadata only (title, DOI or URL), "
                    "with no PDF to ingest."
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{reason} Upload the PDF under Knowledge Builder → Ingestion, "
                    "then reject this suggestion."
                ),
            )

        await self.doc_submissions.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "rejected",
                    "reviewer_id": reviewer_id,
                    "review_comment": comment,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return {"updated": True, "status": "rejected"}

    async def delete_document_submission(self, submission_id: str) -> None:
        """Delete a document submission."""
        try:
            oid = ObjectId(submission_id)
        except (InvalidId, TypeError):
            return
        # Also clean up any ChromaDB / vector embeddings if the doc was processed
        try:
            from advandeb_kb.services.chromadb_service import ChromaDBService

            loop = asyncio.get_event_loop()
            chroma = ChromaDBService()
            await loop.run_in_executor(
                None, chroma.delete_chunks_by_document, submission_id
            )
        except Exception as exc:
            logger.warning(
                "Failed to delete vector chunks for submission %s: %s",
                submission_id,
                exc,
            )
        await self.doc_submissions.delete_one({"_id": oid})

    # ------------------------------------------------------------------
    # Fact submissions
    # ------------------------------------------------------------------

    async def create_fact_submission(
        self,
        data: FactSubmissionCreate,
        creator_id: str,
    ) -> FactSubmission:
        """Create a fact submission for curator review."""
        doc = data.model_dump()
        doc.update(
            {
                "creator_id": creator_id,
                "status": "suggestion",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        result = await self.fact_submissions.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return FactSubmission(**doc)

    async def get_fact_submission(self, submission_id: str) -> Optional[FactSubmission]:
        try:
            oid = ObjectId(submission_id)
        except (InvalidId, TypeError):
            return None
        doc = await self.fact_submissions.find_one({"_id": oid})
        if doc:
            doc["_id"] = str(doc["_id"])
            return FactSubmission(**doc)
        return None

    async def list_fact_submissions(
        self,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None,
        creator_id: Optional[str] = None,
    ) -> List[FactSubmission]:
        query: dict = {}
        if status_filter:
            query["status"] = status_filter
        if creator_id is not None:
            query["creator_id"] = creator_id
        cursor = (
            self.fact_submissions.find(query)
            .skip(skip)
            .limit(limit)
            .sort("created_at", -1)
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(FactSubmission(**doc))
        return results

    async def approve_fact_submission(
        self,
        submission_id: str,
        reviewer_id: str,
        new_status: str,  # "published" | "rejected" | "pending_review"
        review_comment: Optional[str] = None,
    ) -> dict:
        try:
            oid = ObjectId(submission_id)
        except (InvalidId, TypeError):
            return {"updated": False, "error": "Fact submission not found"}
        result = await self.fact_submissions.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": new_status,
                    "review_status": new_status,
                    "reviewer_id": reviewer_id,
                    "review_comment": review_comment,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        if result.matched_count == 0:
            return {"updated": False, "error": "Fact submission not found"}
        return {"updated": True, "status": new_status}

    # ------------------------------------------------------------------
    # Stylized fact submissions
    # ------------------------------------------------------------------

    async def create_sf_submission(
        self,
        data: StylizedFactSubmissionCreate,
        creator_id: str,
    ) -> StylizedFactSubmission:
        doc = data.model_dump()
        doc.update(
            {
                "creator_id": creator_id,
                "status": "suggestion",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        result = await self.sf_submissions.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return StylizedFactSubmission(**doc)

    async def list_sf_submissions(
        self,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None,
        creator_id: Optional[str] = None,
    ) -> List[StylizedFactSubmission]:
        query: dict = {}
        if status_filter:
            query["status"] = status_filter
        if creator_id is not None:
            query["creator_id"] = creator_id
        cursor = (
            self.sf_submissions.find(query)
            .skip(skip)
            .limit(limit)
            .sort("created_at", -1)
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(StylizedFactSubmission(**doc))
        return results

    async def approve_sf_submission(
        self,
        submission_id: str,
        reviewer_id: str,
        new_status: str,  # "published" | "rejected"
        review_comment: Optional[str] = None,
    ) -> dict:
        try:
            oid = ObjectId(submission_id)
        except (InvalidId, TypeError):
            return {"updated": False, "error": "Stylized fact submission not found"}
        result = await self.sf_submissions.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": new_status,
                    "reviewer_id": reviewer_id,
                    "review_comment": review_comment,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        if result.matched_count == 0:
            return {"updated": False, "error": "Stylized fact submission not found"}
        return {"updated": True, "status": new_status}
