"""
IngestionService — manages ingestion batches and their per-file jobs.

Intentionally thin: it only creates/queries MongoDB records.
Heavy processing (PDF extraction, fact extraction, SF matching) is done
inside Celery tasks that call into DataProcessingService and AgentService.
"""
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from advandeb_kb.config.settings import settings
from advandeb_kb.models.ingestion import IngestionBatch, IngestionJob
from advandeb_kb.models.knowledge import Document


class IngestionService:
    def __init__(self, database: AsyncIOMotorDatabase):
        self.db = database
        self.batches = database.ingestion_batches
        self.jobs = database.ingestion_jobs

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------

    async def create_batch(
        self,
        folders: List[str],
        source_root: Optional[str] = None,
        name: Optional[str] = None,
        general_domain: Optional[str] = None,
    ) -> IngestionBatch:
        batch = IngestionBatch(
            name=name,
            source_root=source_root or settings.PAPERS_ROOT,
            folders=folders,
            general_domain=general_domain,
        )
        await self.batches.insert_one(batch.model_dump(by_alias=True))
        return batch

    async def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        doc = await self.batches.find_one({"_id": ObjectId(batch_id)})
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        return doc

    async def list_batches(
        self,
        limit: int = 20,
        general_domain: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if general_domain:
            query["general_domain"] = general_domain
        cursor = self.batches.find(query).sort("created_at", -1).limit(limit)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def update_batch_status(self, batch_id: ObjectId, status: str) -> None:
        await self.batches.update_one(
            {"_id": batch_id},
            {"$set": {"status": status, "updated_at": datetime.utcnow()}},
        )

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    async def create_jobs_for_batch(self, batch: IngestionBatch) -> int:
        """Scan source_root/folders for PDFs and create one job per file."""
        jobs: List[Dict[str, Any]] = []
        for rel_folder in batch.folders:
            folder_path = os.path.join(batch.source_root, rel_folder)
            if not os.path.isdir(folder_path):
                continue
            for root, _, files in os.walk(folder_path):
                for filename in files:
                    if not filename.lower().endswith(".pdf"):
                        continue
                    abs_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(abs_path, batch.source_root)
                    job = IngestionJob(
                        batch_id=batch.id,
                        source_type="pdf_local",
                        source_path_or_url=rel_path,
                        # Carry the batch domain so workers can tag documents
                        metadata={"general_domain": batch.general_domain} if batch.general_domain else {},
                    )
                    jobs.append(job.model_dump(by_alias=True))

        if not jobs:
            return 0

        await self.jobs.insert_many(jobs)
        await self.batches.update_one(
            {"_id": batch.id},
            {"$set": {"num_files": len(jobs), "updated_at": datetime.utcnow()}},
        )
        return len(jobs)

    async def count_pdfs_in_folders(
        self, folders: List[str], source_root: Optional[str] = None
    ) -> int:
        source_root = source_root or settings.PAPERS_ROOT
        total = 0
        for rel_folder in folders:
            folder_path = os.path.join(source_root, rel_folder)
            if not os.path.isdir(folder_path):
                continue
            for _, _, files in os.walk(folder_path):
                total += sum(1 for f in files if f.lower().endswith(".pdf"))
        return total

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        doc = await self.jobs.find_one({"_id": ObjectId(job_id)})
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        doc["batch_id"] = str(doc["batch_id"])
        if doc.get("document_id"):
            doc["document_id"] = str(doc["document_id"])
        return doc

    async def list_jobs(
        self,
        batch_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if batch_id:
            query["batch_id"] = ObjectId(batch_id)
        if status:
            query["status"] = status
        cursor = self.jobs.find(query).sort("created_at", 1).skip(skip).limit(limit)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            doc["batch_id"] = str(doc["batch_id"])
            if doc.get("document_id"):
                doc["document_id"] = str(doc["document_id"])
            results.append(doc)
        return results

    async def update_job_status(self, job_id: ObjectId, **fields: Any) -> None:
        await self.jobs.update_one(
            {"_id": job_id},
            {"$set": {"updated_at": datetime.utcnow(), **fields}},
        )

    async def link_document_to_job(self, job_id: ObjectId, document: Document) -> None:
        await self.jobs.update_one(
            {"_id": job_id},
            {"$set": {"document_id": document.id, "updated_at": datetime.utcnow()}},
        )
