import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from bson import ObjectId

from advandeb_kb.config.settings import settings
from advandeb_kb.models.ingestion import IngestionBatch, IngestionJob
from advandeb_kb.models.knowledge import Document


class IngestionService:
    """Service for ingestion batches and jobs.

    This service is intentionally thin and synchronous; Celery tasks
    will call into it to create/update MongoDB records.
    """

    def __init__(self, database):
        self.db = database
        self.batches = database.ingestion_batches
        self.jobs = database.ingestion_jobs
        self.documents = database.documents

    async def create_batch(self, folders: List[str], source_root: Optional[str] = None, name: Optional[str] = None) -> IngestionBatch:
        source_root = source_root or settings.PAPERS_ROOT
        batch = IngestionBatch(
            name=name,
            source_root=source_root,
            folders=folders,
            num_files=0,
        )
        data = batch.model_dump(by_alias=True)
        result = await self.batches.insert_one(data)
        data["_id"] = result.inserted_id
        return IngestionBatch(**data)

    async def count_pdfs_in_folders(self, folders: List[str], source_root: Optional[str] = None) -> int:
        source_root = source_root or settings.PAPERS_ROOT
        total = 0
        for rel_folder in folders:
            folder_path = os.path.join(source_root, rel_folder)
            if not os.path.isdir(folder_path):
                continue
            for root, _, files in os.walk(folder_path):
                total += len([f for f in files if f.lower().endswith(".pdf")])
        return total

    async def create_jobs_for_batch(self, batch: IngestionBatch) -> int:
        """Scan folders under the batch source root and create jobs."""
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
                    )
                    jobs.append(job.model_dump(by_alias=True))

        if not jobs:
            return 0

        await self.jobs.insert_many(jobs)
        num_files = len(jobs)
        await self.batches.update_one(
            {"_id": batch.id},
            {"$set": {"num_files": num_files, "updated_at": datetime.utcnow()}},
        )
        return num_files

    async def list_batches(self, limit: int = 20) -> List[Dict[str, Any]]:
        cursor = self.batches.find().sort("created_at", -1).limit(limit)
        results: List[Dict[str, Any]] = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        doc = await self.batches.find_one({"_id": ObjectId(batch_id)})
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        return doc

    async def list_jobs(self, batch_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50, skip: int = 0) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if batch_id:
            query["batch_id"] = ObjectId(batch_id)
        if status:
            query["status"] = status
        cursor = self.jobs.find(query).sort("created_at", 1).skip(skip).limit(limit)
        results: List[Dict[str, Any]] = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            doc["batch_id"] = str(doc["batch_id"])
            if doc.get("document_id"):
                doc["document_id"] = str(doc["document_id"])
            results.append(doc)
        return results

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        doc = await self.jobs.find_one({"_id": ObjectId(job_id)})
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        doc["batch_id"] = str(doc["batch_id"])
        if doc.get("document_id"):
            doc["document_id"] = str(doc["document_id"])
        return doc

    async def update_job_status(self, job_id: ObjectId, **fields: Any) -> None:
        update_fields = {"updated_at": datetime.utcnow(), **fields}
        await self.jobs.update_one({"_id": job_id}, {"$set": update_fields})

    async def link_document_to_job(self, job_id: ObjectId, document: Document) -> None:
        await self.jobs.update_one(
            {"_id": job_id},
            {
                "$set": {
                    "document_id": document.id,
                    "updated_at": datetime.utcnow(),
                }
            },
        )
