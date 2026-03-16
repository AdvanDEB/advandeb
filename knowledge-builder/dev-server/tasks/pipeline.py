"""
Async ingestion and KG-linking pipeline — replaces Celery tasks.

Call via FastAPI BackgroundTasks:
    background_tasks.add_task(run_pdf_job, job_id, db)
    background_tasks.add_task(run_kg_link_batch, db, root_taxid=40674)
"""
import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from advandeb_kb.config.settings import settings
from advandeb_kb.models.ingestion import IngestionJob
from advandeb_kb.models.knowledge import Document, Fact, FactSFRelation

logger = logging.getLogger(__name__)

# Limit concurrent jobs (= concurrent Ollama calls) so the model isn't overwhelmed
_JOB_SEM = asyncio.Semaphore(3)

def _fingerprint(text: str) -> str:
    """Normalized fingerprint for fact deduplication."""
    import re as _re
    norm = _re.sub(r"[^a-z0-9 ]", "", text.lower())
    norm = " ".join(norm.split())
    return norm[:120]  # first 120 normalized chars as key


_STOPWORDS = {
    "that", "with", "from", "this", "have", "been", "which",
    "their", "there", "they", "when", "where", "than", "more",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _set_job_stage(
    db: AsyncIOMotorDatabase,
    job_id: ObjectId,
    stage: str,
    status: str = "running",
    progress: int = 0,
    error_message: Optional[str] = None,
) -> None:
    update: Dict[str, Any] = {
        "stage": stage if stage else "pending",
        "status": status,
        "progress": progress,
        "updated_at": datetime.utcnow(),
    }
    if error_message is not None:
        update["error_message"] = error_message
    await db.ingestion_jobs.update_one({"_id": job_id}, {"$set": update})


def _extract_pdf_text(file_path: str) -> str:
    from PyPDF2 import PdfReader
    text = ""
    with open(file_path, "rb") as f:
        reader = PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() or ""
    # Remove lone surrogates — MongoDB (and Python's utf-8 codec) reject them
    return text.encode("utf-8", errors="ignore").decode("utf-8")


async def _extract_facts(text: str) -> List[str]:
    """Extract facts by calling Ollama directly — no agent framework overhead."""
    import httpx

    model = settings.OLLAMA_MODEL
    system = (
        "You are a scientific fact extractor. "
        "Given text from a biology paper, return ONLY a JSON array of concise factual statements. "
        "Each element must be a plain string. No commentary, no markdown, no keys — just the array."
    )
    # Truncate text to avoid hitting context limits (≈12 000 chars ≈ 3 000 tokens)
    snippet = text[:12000]

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Extract facts from:\n\n{snippet}"},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(f"{settings.OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()
        content = resp.json()["message"]["content"].strip()

    # Parse JSON array; fall back to line splitting if the model added prose
    import json as _json
    try:
        # Strip potential markdown code fences
        clean = content
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        facts = _json.loads(clean)
        if isinstance(facts, list):
            return [str(f) for f in facts if f]
    except (_json.JSONDecodeError, ValueError):
        pass

    # Fallback: one non-empty line = one fact, skip header-like lines
    facts = [
        ln.lstrip("•-*0123456789. ").strip()
        for ln in content.splitlines()
        if len(ln.strip()) > 20
    ]
    return facts[:20]


async def _match_sfs(
    db: AsyncIOMotorDatabase,
    fact_id: ObjectId,
    fact_content: str,
    general_domain: Optional[str],
) -> List[Dict[str, Any]]:
    fact_words = {
        w.lower().strip(".,;:()")
        for w in fact_content.split()
        if len(w) > 4 and w.lower() not in _STOPWORDS
    }
    if not fact_words:
        return []

    pattern = "|".join(re.escape(w) for w in sorted(fact_words))
    relations = []
    async for sf_doc in db.stylized_facts.find(
        {"statement": {"$regex": pattern, "$options": "i"}, "status": "published"},
        {"_id": 1, "statement": 1},
    ).limit(10):
        sf_words = {
            w.lower().strip(".,;:()")
            for w in sf_doc["statement"].split()
            if len(w) > 4 and w.lower() not in _STOPWORDS
        }
        overlap = len(fact_words & sf_words)
        if overlap < 2:
            continue
        confidence = min(0.6, overlap / max(len(fact_words), len(sf_words)))
        relation = FactSFRelation(
            fact_id=fact_id,
            sf_id=sf_doc["_id"],
            relation_type="supports",
            confidence=round(confidence, 2),
            status="suggested",
            created_by="agent",
        )
        relations.append(relation.model_dump(by_alias=True))
    return relations


async def _update_batch_status(db: AsyncIOMotorDatabase, batch_id: ObjectId) -> None:
    statuses = [
        d["status"]
        async for d in db.ingestion_jobs.find(
            {"batch_id": batch_id}, {"status": 1, "_id": 0}
        )
    ]
    if not statuses or {"pending", "queued", "running"} & set(statuses):
        return
    if all(s == "completed" for s in statuses):
        batch_status = "completed"
    elif all(s == "failed" for s in statuses):
        batch_status = "failed"
    else:
        batch_status = "mixed"
    await db.ingestion_batches.update_one(
        {"_id": batch_id},
        {"$set": {"status": batch_status, "updated_at": datetime.utcnow()}},
    )


# ---------------------------------------------------------------------------
# PDF ingestion job
# ---------------------------------------------------------------------------

async def run_pdf_job(job_id: str, db: AsyncIOMotorDatabase) -> None:
    """Process a single PDF through text extraction → fact extraction → SF matching."""
    oid = ObjectId(job_id)
    job_doc = await db.ingestion_jobs.find_one({"_id": oid})
    if not job_doc:
        logger.error("Job %s not found", job_id)
        return

    job = IngestionJob(**job_doc)
    general_domain: Optional[str] = job.metadata.get("general_domain")
    source_path = os.path.join(settings.PAPERS_ROOT, job.source_path_or_url)

    if not os.path.isfile(source_path):
        await _set_job_stage(
            db, job.id, "failed", status="failed",
            error_message=f"File not found: {source_path}",
        )
        return

    try:
        # ---- Stage 1: text extraction ----------------------------------
        await _set_job_stage(db, job.id, "text_extraction", progress=10)
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, _extract_pdf_text, source_path)

        document = Document(
            title=os.path.basename(source_path),
            source_type="pdf_local",
            source_path=job.source_path_or_url,
            content=text,
            general_domain=general_domain,
            processing_status="processing",
        )
        await db.documents.insert_one(document.model_dump(by_alias=True))
        await db.ingestion_jobs.update_one(
            {"_id": job.id},
            {"$set": {"document_id": document.id, "updated_at": datetime.utcnow()}},
        )

        # ---- Stage 2: fact extraction ----------------------------------
        await _set_job_stage(db, job.id, "fact_extraction", progress=30)
        fact_texts: List[str] = await _extract_facts(text)

        fact_ids: List[Optional[ObjectId]] = []
        for fact_text in fact_texts:
            fp = _fingerprint(fact_text)
            existing = await db.facts.find_one({"content_fingerprint": fp})
            if existing:
                # Cross-link this document to the existing fact node
                await db.facts.update_one(
                    {"_id": existing["_id"]},
                    {"$addToSet": {"additional_sources": document.id},
                     "$set": {"updated_at": datetime.utcnow()}},
                )
                fact_ids.append(None)  # no new ID; SF matching skipped for this
            else:
                fact = Fact(
                    content=fact_text,
                    document_id=document.id,
                    content_fingerprint=fp,
                    general_domain=general_domain,
                    confidence=0.8,
                    tags=["pdf", "extracted"],
                    status="pending",
                )
                await db.facts.insert_one(fact.model_dump(by_alias=True))
                fact_ids.append(fact.id)

        await db.documents.update_one(
            {"_id": document.id},
            {"$set": {"processing_status": "completed", "updated_at": datetime.utcnow()}},
        )

        # ---- Stage 3: SF matching --------------------------------------
        await _set_job_stage(db, job.id, "sf_matching", progress=70)
        all_relations: List[Dict[str, Any]] = []
        for fid, ftxt in zip(fact_ids, fact_texts):
            if fid is not None:  # None means fact was merged into existing
                all_relations.extend(await _match_sfs(db, fid, ftxt, general_domain))
        if all_relations:
            await db.fact_sf_relations.insert_many(all_relations)

        # ---- Done ------------------------------------------------------
        await _set_job_stage(db, job.id, "completed", status="completed", progress=100)
        logger.info("Job %s: %d facts, %d SF relations", job_id, len(fact_ids), len(all_relations))

    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        await _set_job_stage(db, job.id, "failed", status="failed", error_message=str(exc))

    await _update_batch_status(db, job.batch_id)


# ---------------------------------------------------------------------------
# Batch worker — single background task for a whole batch
# ---------------------------------------------------------------------------

async def run_batch_worker(batch_id: str, db: AsyncIOMotorDatabase) -> None:
    """Run all queued jobs in a batch with controlled concurrency (max 3 at once)."""
    oid = ObjectId(batch_id)
    job_ids = [
        str(doc["_id"])
        async for doc in db.ingestion_jobs.find(
            {"batch_id": oid, "status": "queued"}, {"_id": 1}
        )
    ]
    logger.info("Batch worker %s: starting %d jobs", batch_id, len(job_ids))

    async def _bounded(job_id: str) -> None:
        async with _JOB_SEM:
            await run_pdf_job(job_id, db)

    await asyncio.gather(*[_bounded(jid) for jid in job_ids])
    await _update_batch_status(db, oid)
    logger.info("Batch worker %s: all jobs done", batch_id)


# ---------------------------------------------------------------------------
# KG linking jobs
# ---------------------------------------------------------------------------

async def run_kg_link_batch(
    db: AsyncIOMotorDatabase,
    root_taxid: Optional[int] = 40674,
    limit: int = 1000,
    skip: int = 0,
    overwrite: bool = False,
) -> None:
    from advandeb_kb.services.kg_builder_service import KGBuilderService
    try:
        svc = KGBuilderService(db)
        await svc.ensure_indexes()
        n = await svc.build_name_index(root_taxid=root_taxid)
        logger.info("KG link: name index %d entries", n)
        result = await svc.link_documents(limit=limit, skip=skip, overwrite=overwrite)
        logger.info("KG link complete: %s", result)
    except Exception:
        logger.exception("KG link batch failed")


async def run_kg_link_agent(
    db: AsyncIOMotorDatabase,
    model: str = "deepseek-r1:latest",
    limit: int = 500,
    skip: int = 0,
    overwrite: bool = False,
) -> None:
    from advandeb_kb.services.kg_linker_agent_service import KGLinkerAgentService
    try:
        svc = KGLinkerAgentService(db)
        result = await svc.link_documents(model=model, limit=limit, skip=skip, overwrite=overwrite)
        logger.info("KG agent link complete: %s", result)
    except Exception:
        logger.exception("KG agent link batch failed")
