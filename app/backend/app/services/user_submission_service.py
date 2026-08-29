"""
User submission service — handles document, fact, and stylized fact suggestions
submitted by users for curator review.

All writes go to the app MongoDB database (advandeb), completely separate from
the KB ArangoDB.  A curator approval triggers ingestion into the KB.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, UploadFile, status

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

    # 50 MB upload limit
    MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024

    async def upload_document_submission(
        self,
        file: UploadFile,
        uploader_id: str,
    ) -> DocumentSubmission:
        """Upload a PDF/text file and create a document submission."""
        # Read in chunks to enforce size limit before allocating unbounded memory
        chunks = []
        total_size = 0
        chunk_size = 64 * 1024  # 64 KB

        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > self.MAX_UPLOAD_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds maximum allowed size of {self.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB",
                )
            chunks.append(chunk)

        content = b"".join(chunks)
        filename = file.filename or ""
        content_type = file.content_type or ""

        text_content: Optional[str] = None

        if filename.lower().endswith(".pdf") or "pdf" in content_type:
            try:
                import io
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(content))
                pages_text = [
                    page.extract_text()
                    for page in reader.pages
                    if page.extract_text()
                ]
                text_content = "\n\n".join(pages_text) or None
            except Exception as exc:
                logger.warning("PDF text extraction failed for %s: %s", filename, exc)
        else:
            try:
                text_content = content.decode("utf-8")
            except Exception:
                text_content = None

        doc = {
            "title": filename,
            "source_type": "upload",
            "content": text_content,
            "metadata": {
                "filename": filename,
                "content_type": content_type,
                "size": len(content),
            },
            "uploader_id": uploader_id,
            "status": "suggestion",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
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
    ) -> List[DocumentSubmission]:
        """List document submissions with optional title search and status filter."""
        query: dict = {}
        if search:
            query["title"] = {"$regex": search, "$options": "i"}
        if status:
            query["status"] = status

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
        """Approve or reject a document submission.

        approve → marks status as 'pending' and triggers KB ingestion pipeline.
        reject  → marks status as 'rejected'.
        """
        try:
            oid = ObjectId(submission_id)
        except (InvalidId, TypeError):
            return {"updated": False, "error": "Submission not found"}

        doc = await self.doc_submissions.find_one({"_id": oid})
        if not doc:
            return {"updated": False, "error": "Submission not found"}

        if action == "reject":
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

        # approve: flip to pending, trigger KB ingestion
        await self.doc_submissions.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "pending",
                    "reviewer_id": reviewer_id,
                    "review_comment": comment,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        batch_id: Optional[str] = None
        try:
            from advandeb_kb.services.ingestion_service import IngestionService
            from advandeb_kb.models.ingestion import IngestionJob as KBIngestionJob
            from app.kb.pipeline import run_pdf_job
            from app.core.database import get_kb_database

            kb_db = get_kb_database()
            service = IngestionService(kb_db)

            source_path: str = (
                doc.get("metadata", {}).get("filename") or doc.get("title", "")
            )
            upload_rel = f"uploads/{source_path}" if source_path else None

            batch = await service.create_batch(["uploads"], general_domain=None)
            batch_id = str(batch.id)

            job = KBIngestionJob(
                batch_id=batch.id,
                source_type="pdf_upload",
                source_path_or_url=upload_rel or source_path,
                metadata={
                    "approved_submission_id": submission_id,
                    "reviewer_id": reviewer_id,
                },
            )
            await kb_db.ingestion_jobs.insert_one(job.model_dump(by_alias=True))
            await kb_db.ingestion_batches.update_one(
                {"_id": batch.id},
                {
                    "$set": {
                        "num_files": 1,
                        "status": "running",
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            loop = asyncio.get_event_loop()
            loop.create_task(
                asyncio.to_thread(
                    lambda: asyncio.run(run_pdf_job(str(job.id), kb_db))
                )
            )
        except Exception as exc:
            logger.error(
                "Failed to create ingestion job for approved submission %s: %s",
                submission_id,
                exc,
            )

        return {"updated": True, "status": "pending", "batch_id": batch_id}

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
    ) -> List[FactSubmission]:
        query: dict = {}
        if status_filter:
            query["status"] = status_filter
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
    ) -> List[StylizedFactSubmission]:
        query: dict = {}
        if status_filter:
            query["status"] = status_filter
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
