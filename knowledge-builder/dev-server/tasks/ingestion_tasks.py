import os
from datetime import datetime
from typing import Any, Dict

from bson import ObjectId

from celery_app import celery_app
from advandeb_kb.config.settings import settings
from advandeb_kb.database.mongodb import mongodb
from advandeb_kb.models.knowledge import Document, Fact
from advandeb_kb.models.ingestion import IngestionJob
from advandeb_kb.services.ingestion_service import IngestionService
from advandeb_kb.services.agent_service import AgentService


async def _get_services() -> IngestionService:
    db = mongodb.database
    return IngestionService(db)


@celery_app.task
def run_batch(batch_id: str, options: Dict[str, Any] | None = None) -> str:
    """Entry point for running an ingestion batch.

    This currently just marks jobs as queued; actual processing is handled
    by per-job tasks. This can be extended to build chains/groups.
    """

    # Celery tasks are sync, so we use Motor's sync behaviour via client
    # or rely on simple PyMongo. For now, keep this task minimal and
    # delegate to per-job tasks created elsewhere.
    return batch_id


@celery_app.task
def process_pdf_job(job_id: str) -> str:
    """Process a single PDF ingestion job.

    This function runs synchronously in Celery workers and uses the
    existing DataProcessingService-like logic, but simplified for batch
    ingestion from the local papers directory.
    """

    from database.mongodb import mongodb  # local import to avoid cycles

    db = mongodb.database
    if db is None:
        raise RuntimeError("MongoDB is not initialized in Celery worker")

    jobs_collection = db.ingestion_jobs
    documents_collection = db.documents
    facts_collection = db.facts

    job_doc = jobs_collection.find_one({"_id": ObjectId(job_id)})
    if not job_doc:
        raise ValueError(f"Job {job_id} not found")

    job = IngestionJob(**job_doc)

    source_path = os.path.join(settings.PAPERS_ROOT, job.source_path_or_url)
    if not os.path.isfile(source_path):
        jobs_collection.update_one(
            {"_id": job.id},
            {
                "$set": {
                    "status": "failed",
                    "error_message": f"File not found: {source_path}",
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        return job_id

    from PyPDF2 import PdfReader

    try:
        jobs_collection.update_one(
            {"_id": job.id},
            {"$set": {"status": "running", "stage": "text_extraction", "updated_at": datetime.utcnow()}},
        )

        # Extract text
        text = ""
        with open(source_path, "rb") as f:
            reader = PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() or ""

        file_size = os.path.getsize(source_path)
        filename = os.path.basename(source_path)

        document = Document(
            filename=filename,
            file_type="pdf",
            file_size=file_size,
            content=text,
            processing_status="processing",
        )
        doc_data = document.model_dump(by_alias=True)
        doc_data["_id"] = ObjectId()
        documents_collection.insert_one(doc_data)

        jobs_collection.update_one(
            {"_id": job.id},
            {
                "$set": {
                    "document_id": doc_data["_id"],
                    "stage": "fact_extraction",
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        # Fact extraction via AgentService (sync wrapper around async)
        from services.agent_service import AgentService  # local import

        agent_service = AgentService(db)
        # We call the async function in a simple event loop
        import asyncio

        async def extract(text_content: str):
            return await agent_service.extract_facts(text_content)

        loop = asyncio.get_event_loop()
        try:
            facts = loop.run_until_complete(extract(text))
        except RuntimeError:
            # If no running loop, create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            facts = loop.run_until_complete(extract(text))

        fact_ids: list[ObjectId] = []
        for fact_text in facts:
            fact = Fact(
                content=fact_text,
                source=f"PDF: {filename}",
                confidence=0.8,
                tags=["pdf", "extracted"],
            )
            fact_dict = fact.model_dump(by_alias=True)
            fact_dict["_id"] = ObjectId()
            result = facts_collection.insert_one(fact_dict)
            fact_ids.append(result.inserted_id)

        documents_collection.update_one(
            {"_id": doc_data["_id"]},
            {
                "$set": {
                    "facts_extracted": fact_ids,
                    "processing_status": "completed",
                    "processed_at": datetime.utcnow(),
                }
            },
        )

        jobs_collection.update_one(
            {"_id": job.id},
            {
                "$set": {
                    "status": "completed",
                    "stage": "completed",
                    "progress": 100,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

    except Exception as exc:  # noqa: BLE001
        jobs_collection.update_one(
            {"_id": job.id},
            {
                "$set": {
                    "status": "failed",
                    "stage": "failed",
                    "error_message": str(exc),
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        raise

    return job_id
