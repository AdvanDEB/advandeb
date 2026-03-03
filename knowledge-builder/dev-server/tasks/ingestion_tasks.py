"""
Celery tasks for batch PDF ingestion.

Tasks run synchronously in Celery workers.  All MongoDB operations use
pymongo (synchronous).  Async operations (LLM fact extraction, SF matching)
are wrapped in asyncio.run().

Pipeline per job:
  1. text_extraction  — read PDF, create Document record
  2. fact_extraction  — extract facts via AgentService, create Fact records
  3. sf_matching      — suggest FactSFRelation links (status="suggested")
  4. completed / failed
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from celery_app import celery_app
from advandeb_kb.config.settings import settings
from advandeb_kb.database.mongodb import get_sync_db
from advandeb_kb.models.knowledge import Document, Fact, FactSFRelation
from advandeb_kb.models.ingestion import IngestionJob

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_job_stage(
    jobs: Any,
    job_id: ObjectId,
    stage: str,
    status: str = "running",
    progress: int = 0,
    error_message: Optional[str] = None,
) -> None:
    update: Dict[str, Any] = {
        "stage": stage,
        "status": status,
        "progress": progress,
        "updated_at": datetime.utcnow(),
    }
    if error_message is not None:
        update["error_message"] = error_message
    jobs.update_one({"_id": job_id}, {"$set": update})


def _extract_pdf_text(file_path: str) -> str:
    from PyPDF2 import PdfReader
    text = ""
    with open(file_path, "rb") as f:
        reader = PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() or ""
    return text


async def _extract_facts(db_url: str, db_name: str, text: str) -> List[str]:
    """Async fact extraction — runs inside asyncio.run() in the Celery task."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from advandeb_kb.services.agent_service import AgentService

    client = AsyncIOMotorClient(db_url)
    try:
        db = client[db_name]
        agent = AgentService(db)
        return await agent.extract_facts(text)
    finally:
        client.close()


async def _match_sfs(
    db_url: str,
    db_name: str,
    fact_id: ObjectId,
    fact_content: str,
    general_domain: Optional[str],
) -> List[Dict[str, Any]]:
    """Suggest FactSFRelation links for a single fact.

    Uses simple keyword overlap: finds SFs whose statement shares significant
    terms with the fact content, then creates 'suggested' relations.
    Returns a list of relation dicts ready for insert_many.
    """
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(db_url)
    try:
        db = client[db_name]

        # Build a set of meaningful words from the fact (>4 chars, not stopwords)
        _STOPWORDS = {
            "that", "with", "from", "this", "have", "been", "which",
            "their", "there", "they", "when", "where", "than", "more",
        }
        fact_words = {
            w.lower().strip(".,;:()")
            for w in fact_content.split()
            if len(w) > 4 and w.lower() not in _STOPWORDS
        }
        if not fact_words:
            return []

        # Regex: match SFs containing any of the significant words
        import re
        pattern = "|".join(re.escape(w) for w in sorted(fact_words))
        cursor = db.stylized_facts.find(
            {"statement": {"$regex": pattern, "$options": "i"}, "status": "published"},
            {"_id": 1, "statement": 1},
        ).limit(10)

        relations = []
        async for sf_doc in cursor:
            sf_words = {
                w.lower().strip(".,;:()")
                for w in sf_doc["statement"].split()
                if len(w) > 4 and w.lower() not in _STOPWORDS
            }
            overlap = len(fact_words & sf_words)
            if overlap < 2:
                continue

            # Confidence proportional to overlap ratio (capped at 0.6 for keyword match)
            confidence = min(0.6, overlap / max(len(fact_words), len(sf_words)))

            relation = FactSFRelation(
                fact_id=fact_id,
                sf_id=sf_doc["_id"],
                relation_type="supports",  # default; curator reviews
                confidence=round(confidence, 2),
                status="suggested",
                created_by="agent",
            )
            relations.append(relation.model_dump(by_alias=True))

        return relations
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@celery_app.task
def run_batch(batch_id: str, options: Dict[str, Any] = None) -> str:
    """Mark all pending jobs in a batch as queued.

    Workers pick them up via process_pdf_job.
    """
    db = get_sync_db()
    db.ingestion_jobs.update_many(
        {"batch_id": ObjectId(batch_id), "status": "pending"},
        {"$set": {"status": "queued", "updated_at": datetime.utcnow()}},
    )
    db.ingestion_batches.update_one(
        {"_id": ObjectId(batch_id)},
        {"$set": {"status": "running", "updated_at": datetime.utcnow()}},
    )
    return batch_id


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def process_pdf_job(self, job_id: str) -> str:
    """Process a single PDF ingestion job through the full pipeline."""
    db = get_sync_db()
    jobs_col = db.ingestion_jobs
    docs_col = db.documents
    facts_col = db.facts
    relations_col = db.fact_sf_relations

    job_doc = jobs_col.find_one({"_id": ObjectId(job_id)})
    if not job_doc:
        raise ValueError(f"Job {job_id} not found")

    job = IngestionJob(**job_doc)
    general_domain: Optional[str] = job.metadata.get("general_domain")

    source_path = os.path.join(settings.PAPERS_ROOT, job.source_path_or_url)
    if not os.path.isfile(source_path):
        _set_job_stage(
            jobs_col, job.id, "failed", status="failed",
            error_message=f"File not found: {source_path}",
        )
        return job_id

    try:
        # ---- Stage 1: text extraction ----------------------------------
        _set_job_stage(jobs_col, job.id, "text_extraction", progress=10)

        text = _extract_pdf_text(source_path)
        filename = os.path.basename(source_path)
        file_size = os.path.getsize(source_path)

        document = Document(
            title=filename,
            source_type="pdf_local",
            source_path=job.source_path_or_url,
            content=text,
            general_domain=general_domain,
            processing_status="processing",
        )
        doc_data = document.model_dump(by_alias=True)
        docs_col.insert_one(doc_data)

        jobs_col.update_one(
            {"_id": job.id},
            {"$set": {
                "document_id": document.id,
                "stage": "fact_extraction",
                "progress": 30,
                "updated_at": datetime.utcnow(),
            }},
        )

        # ---- Stage 2: fact extraction ----------------------------------
        _set_job_stage(jobs_col, job.id, "fact_extraction", progress=30)

        fact_texts: List[str] = asyncio.run(
            _extract_facts(settings.MONGODB_URL, settings.DATABASE_NAME, text)
        )

        fact_ids: List[ObjectId] = []
        for fact_text in fact_texts:
            fact = Fact(
                content=fact_text,
                document_id=document.id,
                general_domain=general_domain,
                confidence=0.8,
                tags=["pdf", "extracted"],
                status="pending",
            )
            facts_col.insert_one(fact.model_dump(by_alias=True))
            fact_ids.append(fact.id)

        docs_col.update_one(
            {"_id": document.id},
            {"$set": {
                "processing_status": "completed",
                "updated_at": datetime.utcnow(),
            }},
        )

        # ---- Stage 3: SF matching --------------------------------------
        _set_job_stage(jobs_col, job.id, "sf_matching", progress=70)

        all_relations: List[Dict[str, Any]] = []
        for i, (fact_id, fact_text) in enumerate(zip(fact_ids, fact_texts)):
            relations = asyncio.run(
                _match_sfs(
                    settings.MONGODB_URL,
                    settings.DATABASE_NAME,
                    fact_id,
                    fact_text,
                    general_domain,
                )
            )
            all_relations.extend(relations)

        if all_relations:
            relations_col.insert_many(all_relations)

        # ---- Done ------------------------------------------------------
        _set_job_stage(
            jobs_col, job.id, "completed",
            status="completed", progress=100,
        )
        logger.info(
            f"Job {job_id}: extracted {len(fact_ids)} facts, "
            f"suggested {len(all_relations)} SF relations"
        )

    except Exception as exc:
        logger.exception(f"Job {job_id} failed: {exc}")
        _set_job_stage(
            jobs_col, job.id, "failed",
            status="failed",
            error_message=str(exc),
        )
        raise self.retry(exc=exc)

    # Update batch status if all jobs are done
    _update_batch_status(db, job.batch_id)
    return job_id


def _update_batch_status(db: Any, batch_id: ObjectId) -> None:
    """Set batch status to completed/mixed/failed once all jobs are done."""
    statuses = [
        d["status"]
        for d in db.ingestion_jobs.find(
            {"batch_id": batch_id}, {"status": 1, "_id": 0}
        )
    ]
    if not statuses:
        return
    still_running = {"pending", "queued", "running"} & set(statuses)
    if still_running:
        return  # some jobs still in progress

    if all(s == "completed" for s in statuses):
        batch_status = "completed"
    elif all(s == "failed" for s in statuses):
        batch_status = "failed"
    else:
        batch_status = "mixed"

    db.ingestion_batches.update_one(
        {"_id": batch_id},
        {"$set": {"status": batch_status, "updated_at": datetime.utcnow()}},
    )
