"""
Async ingestion and KG-linking pipeline — runs as FastAPI BackgroundTasks.

Call via FastAPI BackgroundTasks:
    background_tasks.add_task(run_pdf_job, job_id, db)
    background_tasks.add_task(run_kg_link_batch, db, root_taxid=40674)
"""
import asyncio
import logging
import os
import re
import subprocess
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from advandeb_kb.config.settings import settings
from advandeb_kb.models.ingestion import IngestionJob
from advandeb_kb.models.knowledge import Document, Fact, FactSFRelation
from advandeb_kb.services.chunking_service import ChunkingService
from advandeb_kb.services.embedding_service import EmbeddingService
from advandeb_kb.services.chromadb_service import ChromaDBService
from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue

logger = logging.getLogger(__name__)

# Module-level singletons — loaded once per process (heavy models)
_chunker: Optional[ChunkingService] = None
_embedder: Optional[EmbeddingService] = None
_chroma: Optional[ChromaDBService] = None


def _get_embedding_services():
    global _chunker, _embedder, _chroma
    if _chunker is None:
        _chunker = ChunkingService(chunk_size=512, overlap=128)
    if _embedder is None:
        _embedder = EmbeddingService()
    if _chroma is None:
        _chroma = ChromaDBService()
    return _chunker, _embedder, _chroma


# ---------------------------------------------------------------------------
# Dynamic concurrency estimation
# ---------------------------------------------------------------------------

# Each pipeline job holds roughly this much system RAM while running
# (PDF text buffer + fact list + relation list + Python overhead).
_RAM_PER_JOB_GB = 1.5

# Each pipeline job makes 2 sequential Ollama calls.  When multiple jobs run
# in parallel those calls queue up inside Ollama.  Ollama handles concurrent
# requests to the same model by *serialising* LLM inference — so there is no
# speed gain from having more parallel jobs than the number of model instances
# Ollama can serve.  We therefore derive the concurrency limit primarily from
# how many model instances can fit in free VRAM, with CPU and RAM as secondary
# guards.
_MAX_CONCURRENCY = 12   # hard ceiling regardless of resources
_MIN_CONCURRENCY = 1


def _free_vram_mib() -> Dict[int, float]:
    """Return {gpu_index: free_mib} by parsing nvidia-smi output.
    Returns {} if nvidia-smi is unavailable."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=index,memory.free",
             "--format=csv,noheader,nounits"],
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).decode()
        result = {}
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 2:
                result[int(parts[0])] = float(parts[1])
        return result
    except Exception:
        return {}


def _ollama_model_vram_mib() -> float:
    """Return the VRAM footprint (MiB) of the currently loaded Ollama model.
    Returns 0 if Ollama is unreachable or no model is loaded."""
    try:
        import urllib.request
        with urllib.request.urlopen(
            f"{settings.OLLAMA_BASE_URL}/api/ps", timeout=3
        ) as resp:
            data = json.loads(resp.read())
        models = data.get("models", [])
        if not models:
            return 0.0
        # Use the first (or only) loaded model — the one the pipeline calls
        target = settings.OLLAMA_MODEL.split(":")[0].lower()
        for m in models:
            if target in m.get("name", "").lower():
                return m.get("size_vram", 0) / (1024 * 1024)
        # Fallback: largest loaded model
        return max(m.get("size_vram", 0) for m in models) / (1024 * 1024)
    except Exception:
        return 0.0


def compute_job_concurrency() -> int:
    """
    Estimate the safe number of parallel ingestion jobs based on available
    hardware resources.

    Strategy
    --------
    1. INGESTION_CONCURRENCY env var → always wins (manual override).
    2. Query nvidia-smi for per-GPU free VRAM and Ollama /api/ps for the
       loaded model's VRAM footprint.
       - For each GPU count how many additional model copies fit in free VRAM
         (with a 10 % headroom margin).
       - Sum across all GPUs → *vram_parallel*: the number of simultaneous
         Ollama inferences possible.
       Note: if Ollama is not using GPUs (CPU-only) vram_parallel is set to 1
       because the LLM is already the bottleneck and more parallel requests
       just add latency.
    3. Guard by available system RAM: floor(available_ram / RAM_PER_JOB_GB).
    4. Guard by CPU count: floor(cpu_count / 4)  (each job uses ~4 cores peak).
    5. Final value = clamp(min(vram_parallel, ram_limit, cpu_limit),
                           _MIN_CONCURRENCY, _MAX_CONCURRENCY).

    The result is logged at startup so it is visible in server logs.
    """
    # --- Manual override (env var or settings) ---
    env_val = os.environ.get("INGESTION_CONCURRENCY", "").strip()
    settings_val = getattr(settings, "INGESTION_CONCURRENCY", 0)
    override = int(env_val) if env_val.isdigit() else settings_val
    if override > 0:
        logger.info(
            "Ingestion concurrency: %d (manual override via INGESTION_CONCURRENCY)", override
        )
        return override

    # --- VRAM estimate ---
    model_vram = _ollama_model_vram_mib()
    free_vram = _free_vram_mib()

    if model_vram > 0 and free_vram:
        headroom = 0.90  # leave 10 % free per GPU
        vram_parallel = 0
        for gpu_idx, free_mib in free_vram.items():
            usable = free_mib * headroom
            # The model is already loaded on at least one GPU; count that slot
            # plus however many more copies fit in the remaining free VRAM.
            copies = int(usable / model_vram)
            vram_parallel += copies
        # Always guarantee at least 1 (already-loaded model)
        vram_parallel = max(1, vram_parallel)
        logger.info(
            "VRAM estimate: model=%.0f MiB, free per GPU=%s → vram_parallel=%d",
            model_vram,
            {k: f"{v:.0f}" for k, v in free_vram.items()},
            vram_parallel,
        )
    elif model_vram == 0 and free_vram:
        # GPUs present but model not loaded / CPU-only inference
        vram_parallel = 1
        logger.info(
            "VRAM estimate: Ollama model not loaded on GPU — assuming CPU inference, vram_parallel=1"
        )
    else:
        # No GPU / nvidia-smi unavailable → CPU-only assumption
        vram_parallel = 1
        logger.info("VRAM estimate: nvidia-smi unavailable — assuming CPU inference, vram_parallel=1")

    # --- RAM estimate ---
    try:
        with open("/proc/meminfo") as f:
            meminfo = {
                parts[0].rstrip(":"): int(parts[1])
                for line in f
                if len(parts := line.split()) >= 2
            }
        available_ram_gb = meminfo.get("MemAvailable", 0) / (1024 * 1024)
    except Exception:
        available_ram_gb = 8.0  # conservative fallback
    ram_limit = max(1, int(available_ram_gb / _RAM_PER_JOB_GB))

    # --- CPU estimate ---
    try:
        cpu_count = os.cpu_count() or 4
    except Exception:
        cpu_count = 4
    cpu_limit = max(1, cpu_count // 4)

    # --- Final value ---
    concurrency = min(vram_parallel, ram_limit, cpu_limit)
    concurrency = max(_MIN_CONCURRENCY, min(_MAX_CONCURRENCY, concurrency))

    logger.info(
        "Ingestion concurrency estimate: vram_parallel=%d ram_limit=%d "
        "(%.0f GB avail / %.1f GB per job) cpu_limit=%d (%d cores / 4) → chosen=%d",
        vram_parallel, ram_limit, available_ram_gb, _RAM_PER_JOB_GB,
        cpu_limit, cpu_count, concurrency,
    )
    return concurrency


# Semaphore is initialised lazily on first batch run so that Ollama is
# already up and the VRAM query returns meaningful numbers.
_JOB_SEM: Optional[asyncio.Semaphore] = None


def _get_job_sem() -> asyncio.Semaphore:
    """Return (and lazily initialise) the per-process job semaphore."""
    global _JOB_SEM
    if _JOB_SEM is None:
        n = compute_job_concurrency()
        _JOB_SEM = asyncio.Semaphore(n)
    return _JOB_SEM

# ---------------------------------------------------------------------------
# Cooperative batch cancellation — stored in MongoDB so any worker process
# sees a stop signal regardless of which worker received the HTTP request.
# ---------------------------------------------------------------------------

async def _is_cancelled(db: AsyncIOMotorDatabase, batch_id: str) -> bool:
    """Return True if the batch has been stop-requested (checked via MongoDB)."""
    doc = await db.ingestion_batches.find_one(
        {"_id": ObjectId(batch_id)},
        {"status": 1},
    )
    return doc is not None and doc.get("status") == "stopped"


def cancel_batch(batch_id: str) -> None:  # noqa: ARG001
    """
    Kept for API compatibility — the stop endpoint writes the 'stopped' status
    to MongoDB directly, so in-process signalling is no longer required.
    This function is now a no-op; cancellation is detected via _is_cancelled().
    """


def uncancel_batch(batch_id: str) -> None:  # noqa: ARG001
    """No-op — cancellation state lives in MongoDB, not in process memory."""


def _fingerprint(text: str) -> str:
    """Normalized fingerprint for fact deduplication."""
    import re as _re
    norm = _re.sub(r"[^a-z0-9 ]", "", text.lower())
    norm = " ".join(norm.split())
    return norm[:120]


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
    return text.encode("utf-8", errors="ignore").decode("utf-8")


_DOI_RE = re.compile(
    r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9a-z]+)",
    re.IGNORECASE,
)


def _extract_doi_references(text: str) -> List[str]:
    """Extract all unique DOI strings from document text (for citation edges)."""
    dois = _DOI_RE.findall(text)
    # Normalise: lowercase, strip trailing punctuation
    seen: set = set()
    result: List[str] = []
    for doi in dois:
        doi = doi.rstrip(".,;)")
        doi_lower = doi.lower()
        if doi_lower not in seen:
            seen.add(doi_lower)
            result.append(doi_lower)
    return result


async def _extract_facts(text: str) -> List[str]:
    """Extract facts by calling Ollama directly."""
    import httpx

    model = settings.OLLAMA_MODEL
    system = (
        "You are a scientific fact extractor. "
        "Given text from a biology paper, return ONLY a JSON array of concise factual statements. "
        "Each element must be a plain string. No commentary, no markdown, no keys — just the array."
    )
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

    import json as _json
    try:
        clean = content
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        facts = _json.loads(clean)
        if isinstance(facts, list):
            return [str(f) for f in facts if f]
    except (_json.JSONDecodeError, ValueError):
        pass

    facts = [
        ln.lstrip("•-*0123456789. ").strip()
        for ln in content.splitlines()
        if len(ln.strip()) > 20
    ]
    return facts[:20]


async def _classify_sf_relations(
    fact_content: str,
    candidates: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Call Ollama once to classify whether a fact *supports* or *opposes* each
    candidate stylized fact, and get a confidence score.

    Returns a mapping  sf_id (str) → {"relation_type": str, "confidence": float}.
    Falls back to {"relation_type": "supports", "confidence": 0.4} per candidate
    if the LLM call fails or returns an unparseable response.
    """
    import httpx
    import json as _json

    # Build a numbered list so the LLM can reference each SF by index
    sf_lines = "\n".join(
        f"[{i}] {c['statement']}" for i, c in enumerate(candidates)
    )
    system = (
        "You are a scientific knowledge linker. "
        "Given a fact and a numbered list of stylized facts, return ONLY a JSON array. "
        "Each element must be an object with: "
        "'index' (integer, 0-based), "
        "'relation_type' (exactly 'supports' or 'opposes'), "
        "'confidence' (float 0-1). "
        "Include an entry for every stylized fact that the given fact either "
        "supports OR opposes. Omit unrelated ones. "
        "Return [] if none are related. No markdown, no commentary."
    )
    prompt = (
        f"Fact: {fact_content}\n\n"
        f"Stylized facts:\n{sf_lines}\n\n"
        "For each stylized fact above, does the given fact support or oppose it?"
    )
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.1},
    }

    # Default fallback — treated as "supports" with low confidence
    fallback = {
        str(c["_id"]): {"relation_type": "supports", "confidence": 0.4}
        for c in candidates
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat", json=payload
            )
            resp.raise_for_status()
            raw = resp.json()["message"]["content"].strip()

        clean = raw
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        matches = _json.loads(clean)
        if not isinstance(matches, list):
            return fallback

        result: Dict[str, Dict[str, Any]] = {}
        for m in matches:
            if not isinstance(m, dict):
                continue
            idx = m.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
                continue
            rel_type = m.get("relation_type", "supports")
            if rel_type not in ("supports", "opposes"):
                rel_type = "supports"
            confidence = float(m.get("confidence", 0.5))
            sf_id = str(candidates[idx]["_id"])
            result[sf_id] = {"relation_type": rel_type, "confidence": confidence}

        # Merge: keep LLM result where available, fall back otherwise
        for sf_id, fb in fallback.items():
            if sf_id not in result:
                result[sf_id] = fb
        return result

    except Exception as exc:
        logger.warning("SF relation classification failed (using fallback): %s", exc)
        return fallback


async def _match_sfs(
    db: AsyncIOMotorDatabase,
    fact_id: ObjectId,
    fact_content: str,
    general_domain: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Two-phase SF matching:
      Phase 1 — keyword overlap pre-filter (fast, no LLM) to find candidate SFs.
      Phase 2 — LLM classification to determine supports / opposes and confidence.
    """
    fact_words = {
        w.lower().strip(".,;:()")
        for w in fact_content.split()
        if len(w) > 4 and w.lower() not in _STOPWORDS
    }
    if not fact_words:
        return []

    # --- Phase 1: keyword pre-filter ---
    pattern = "|".join(re.escape(w) for w in sorted(fact_words))
    candidates: List[Dict[str, Any]] = []
    async for sf_doc in db.stylized_facts.find(
        {"statement": {"$regex": pattern, "$options": "i"}, "status": "published"},
        {"_id": 1, "statement": 1},
    ).limit(15):
        sf_words = {
            w.lower().strip(".,;:()")
            for w in sf_doc["statement"].split()
            if len(w) > 4 and w.lower() not in _STOPWORDS
        }
        if len(fact_words & sf_words) >= 2:
            candidates.append(sf_doc)

    if not candidates:
        return []

    # --- Phase 2: LLM classification (supports vs opposes) ---
    classifications = await _classify_sf_relations(fact_content, candidates)

    relations = []
    for sf_doc in candidates:
        sf_id_str = str(sf_doc["_id"])
        cls = classifications.get(sf_id_str, {"relation_type": "supports", "confidence": 0.4})
        relation = FactSFRelation(
            fact_id=fact_id,
            sf_id=sf_doc["_id"],
            relation_type=cls["relation_type"],
            confidence=round(min(1.0, max(0.0, cls["confidence"])), 2),
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
    """Process a single PDF: text extraction → fact extraction → SF matching → embedding."""
    oid = ObjectId(job_id)
    job_doc = await db.ingestion_jobs.find_one({"_id": oid})
    if not job_doc:
        logger.error("Job %s not found", job_id)
        return

    job = IngestionJob(**job_doc)
    general_domain: Optional[str] = job.metadata.get("general_domain")
    batch_id_str = str(job.batch_id)

    # Skip if already processed (detected at scan time or by a previous run)
    if job.already_processed or await db.documents.find_one(
        {"source_path": job.source_path_or_url, "processing_status": "completed"}
    ):
        await db.ingestion_jobs.update_one(
            {"_id": oid},
            {"$set": {"already_processed": True, "status": "completed",
                      "stage": "completed", "progress": 100,
                      "updated_at": datetime.utcnow()}},
        )
        await _update_batch_status(db, job.batch_id)
        logger.info("Job %s: skipped — document already processed", job_id)
        return

    source_path = os.path.join(settings.PAPERS_ROOT, job.source_path_or_url)

    if not os.path.isfile(source_path):
        await _set_job_stage(
            db, job.id, "failed", status="failed",
            error_message=f"File not found: {source_path}",
        )
        await _update_batch_status(db, job.batch_id)
        return

    try:
        # ---- Stage 1: text extraction ----------------------------------
        if await _is_cancelled(db, batch_id_str):
            await _set_job_stage(db, job.id, "failed", status="cancelled",
                                 error_message="batch stopped by user")
            return

        await _set_job_stage(db, job.id, "text_extraction", progress=10)
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _extract_pdf_text, source_path)

        references = _extract_doi_references(text)

        document = Document(
            title=os.path.basename(source_path),
            source_type="pdf_local",
            source_path=job.source_path_or_url,
            content=text,
            general_domain=general_domain,
            processing_status="processing",
            references=references,
        )
        await db.documents.insert_one(document.model_dump(by_alias=True))
        logger.info("Job %s: extracted %d DOI references", job_id, len(references))
        await db.ingestion_jobs.update_one(
            {"_id": job.id},
            {"$set": {"document_id": document.id, "updated_at": datetime.utcnow()}},
        )

        # ---- Stage 2: fact extraction ----------------------------------
        if await _is_cancelled(db, batch_id_str):
            await _set_job_stage(db, job.id, "failed", status="cancelled",
                                 error_message="batch stopped by user")
            return

        await _set_job_stage(db, job.id, "fact_extraction", progress=30)
        fact_texts: List[str] = await _extract_facts(text)

        fact_ids: List[Optional[ObjectId]] = []
        for fact_text in fact_texts:
            fp = _fingerprint(fact_text)
            existing = await db.facts.find_one({"content_fingerprint": fp})
            if existing:
                await db.facts.update_one(
                    {"_id": existing["_id"]},
                    {"$addToSet": {"additional_sources": document.id},
                     "$set": {"updated_at": datetime.utcnow()}},
                )
                fact_ids.append(None)
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
        if await _is_cancelled(db, batch_id_str):
            await _set_job_stage(db, job.id, "failed", status="cancelled",
                                 error_message="batch stopped by user")
            return

        await _set_job_stage(db, job.id, "sf_matching", progress=70)
        all_relations: List[Dict[str, Any]] = []
        for fid, ftxt in zip(fact_ids, fact_texts):
            if fid is not None:
                all_relations.extend(await _match_sfs(db, fid, ftxt, general_domain))
        if all_relations:
            await db.fact_sf_relations.insert_many(all_relations)

        graph_rebuild_queue.mark_dirty("sf_support")
        graph_rebuild_queue.mark_dirty("citation")

        # ---- Stage 4: chunking + embedding → ChromaDB -----------------
        if await _is_cancelled(db, batch_id_str):
            await _set_job_stage(db, job.id, "failed", status="cancelled",
                                 error_message="batch stopped by user")
            return

        await _set_job_stage(db, job.id, "embedding", progress=85)
        chunk_count = 0
        if text.strip():
            try:
                chunker, embedder, chroma = _get_embedding_services()
                doc_id_str = str(document.id)

                chunks = await asyncio.get_running_loop().run_in_executor(
                    None, chunker.chunk_document, text, doc_id_str
                )

                if chunks:
                    metadatas = []
                    for chunk in chunks:
                        meta = chunk.to_chromadb_metadata()
                        meta["title"] = document.title or ""
                        meta["year"] = document.year or 0 if hasattr(document, "year") else 0
                        meta["doi"] = document.doi or "" if hasattr(document, "doi") else ""
                        meta["general_domain"] = general_domain or ""
                        meta["source_path"] = job.source_path_or_url
                        metadatas.append(meta)

                    texts_to_embed = [c.text for c in chunks]
                    embeddings = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: embedder.embed_batch(texts_to_embed, show_progress=False)
                    )

                    await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: chroma.add_chunks_batch(
                            chunk_ids=[c.chunk_id for c in chunks],
                            texts=texts_to_embed,
                            embeddings=embeddings,
                            metadatas=metadatas,
                        ),
                    )

                    now = datetime.utcnow()
                    chunk_docs = [
                        {
                            "chunk_id": c.chunk_id,
                            "document_id": document.id,
                            "chunk_index": c.chunk_index,
                            "text": c.text,
                            "char_start": c.char_start,
                            "char_end": c.char_end,
                            "embedded": True,
                            "created_at": now,
                        }
                        for c in chunks
                    ]
                    for cdoc in chunk_docs:
                        await db.chunks.replace_one(
                            {"chunk_id": cdoc["chunk_id"]}, cdoc, upsert=True
                        )

                    chunk_count = len(chunks)
                    await db.documents.update_one(
                        {"_id": document.id},
                        {"$set": {
                            "embedding_status": "embedded",
                            "num_chunks": chunk_count,
                            "updated_at": datetime.utcnow(),
                        }},
                    )
                    logger.info("Job %s: embedded %d chunks into ChromaDB", job_id, chunk_count)
            except Exception as embed_exc:
                logger.warning("Job %s: embedding failed (non-fatal): %s", job_id, embed_exc)
                await db.documents.update_one(
                    {"_id": document.id},
                    {"$set": {"embedding_status": "failed", "updated_at": datetime.utcnow()}},
                )

        # ---- Done ------------------------------------------------------
        await _set_job_stage(db, job.id, "completed", status="completed", progress=100)
        logger.info(
            "Job %s: %d facts, %d SF relations, %d chunks embedded",
            job_id, len(fact_ids), len(all_relations), chunk_count,
        )

    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        await _set_job_stage(db, job.id, "failed", status="failed", error_message=str(exc))

    finally:
        # Always update the batch status, even if CancelledError or another
        # non-Exception is raised (e.g. during server shutdown).
        await _update_batch_status(db, job.batch_id)


# ---------------------------------------------------------------------------
# Batch worker
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
        async with _get_job_sem():
            await run_pdf_job(job_id, db)

    try:
        await asyncio.gather(*[_bounded(jid) for jid in job_ids])
    finally:
        # Always finalize batch status even if gather is interrupted.
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
        graph_rebuild_queue.mark_dirty("knowledge_graph")
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
        graph_rebuild_queue.mark_dirty("knowledge_graph")
    except Exception:
        logger.exception("KG agent link batch failed")
