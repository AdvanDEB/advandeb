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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReplaceOne

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
        "updated_at": datetime.now(timezone.utc),
    }
    if error_message is not None:
        update["error_message"] = error_message
    await db.ingestion_jobs.update_one({"_id": job_id}, {"$set": update})


def _extract_pdf_text(file_path: str) -> str:
    from PyPDF2 import PdfReader
    text = ""
    with open(file_path, "rb") as f:
        reader = PdfReader(f)
        # Some PDFs are encrypted with an empty owner password (print-locked
        # but readable).  Try to decrypt with an empty password before giving
        # up; pycryptodome must be installed for AES-encrypted files.
        if reader.is_encrypted:
            try:
                result = reader.decrypt("")
                if result == 0:
                    raise ValueError("PDF is password-protected and cannot be decrypted without a password")
            except Exception as exc:
                raise ValueError(f"Could not decrypt PDF: {exc}") from exc
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


# ---------------------------------------------------------------------------
# Bibliographic metadata enrichment (filename parsing + CrossRef + OpenAlex)
# ---------------------------------------------------------------------------

# Matches Zotero-style names: "Author et al. - 2019 - Title fragment..."
_LONG_FILENAME_RE = re.compile(
    r"^(.+?)\s*[-–—]\s*(19[6-9]\d|20[0-2]\d)\s*[-–—]\s*(.+?)$",
    re.IGNORECASE,
)
# 4-digit year anywhere in filename
_YEAR4_RE = re.compile(r"(19[6-9]\d|20[0-2]\d)")

_CROSSREF_HEADERS = {
    "User-Agent": "advandeb-knowledge-builder/1.0 (mailto:domagojhack@gmail.com)",
}


def _parse_pdf_filename(filename: str) -> Dict[str, Any]:
    """Extract year, authors_raw, and paper_title from a PDF filename (best-effort)."""
    base = filename.removesuffix(".pdf").removesuffix(".PDF").strip()

    m = _LONG_FILENAME_RE.match(base)
    if m:
        year_str = m.group(2)
        year = int(year_str) if len(year_str) == 4 else (1900 + int(year_str) if int(year_str) >= 60 else 2000 + int(year_str))
        return {
            "year": year,
            "authors_raw": m.group(1).strip(),
            "paper_title": m.group(3).strip().rstrip(". "),
        }

    year = None
    m4 = _YEAR4_RE.search(base)
    if m4:
        year = int(m4.group(1))

    parts = re.split(r"\s*[-–—]\s+", base, maxsplit=1)
    if len(parts) == 2:
        return {"year": year, "authors_raw": parts[0].strip(), "paper_title": parts[1].strip()}
    return {"year": year, "authors_raw": None, "paper_title": None}


def _parse_crossref_authors(item: Dict[str, Any]) -> List[str]:
    """Format CrossRef author list as ['Given Family', ...]."""
    result = []
    for a in item.get("author") or []:
        given = a.get("given", "")
        family = a.get("family", "")
        name = f"{given} {family}".strip() if given else family
        if name:
            result.append(name)
    return result


def _parse_crossref_year(item: Dict[str, Any]) -> Optional[int]:
    pub = item.get("published") or item.get("published-print") or item.get("published-online")
    if pub:
        dp = pub.get("date-parts", [[]])
        if dp and dp[0]:
            try:
                return int(dp[0][0])
            except (TypeError, ValueError):
                pass
    return None


def _parse_crossref_journal(item: Dict[str, Any]) -> Optional[str]:
    titles = item.get("container-title") or []
    return titles[0].strip() if titles else None


def _clean_crossref_abstract(raw: Optional[str]) -> Optional[str]:
    """Strip JATS XML tags that CrossRef sometimes wraps abstracts in."""
    if not raw:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


async def _crossref_lookup(title: str, year: Optional[int]) -> Optional[Dict[str, Any]]:
    """
    Query CrossRef for the best-matching item given a title and optional year.
    Returns the raw CrossRef item dict, or None on failure/no match.
    """
    import httpx

    params: Dict[str, Any] = {
        "query.title": title,
        "rows": 3,
        "select": "DOI,title,author,published,published-print,published-online,"
                  "container-title,abstract,reference",
    }
    if year:
        params["filter"] = f"from-pub-date:{year - 1},until-pub-date:{year + 1}"

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                headers=_CROSSREF_HEADERS, follow_redirects=True, timeout=15.0
            ) as client:
                resp = await client.get(
                    "https://api.crossref.org/works", params=params
                )
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code != 200:
                return None
            items = resp.json().get("message", {}).get("items", [])
            if not items:
                return None
            # Pick the item whose title overlaps most with our query title
            def _sim(item: Dict[str, Any]) -> float:
                cr_title = (item.get("title") or [""])[0].lower()
                qa = set(re.findall(r"\w+", title.lower()))
                qb = set(re.findall(r"\w+", cr_title))
                return len(qa & qb) / max(len(qa), len(qb), 1)
            best = max(items, key=_sim)
            if _sim(best) < 0.35:
                return None
            return best
        except Exception as exc:
            logger.debug("CrossRef lookup failed (attempt %d): %s", attempt + 1, exc)
            if attempt < 2:
                await asyncio.sleep(1)
    return None


# ---------------------------------------------------------------------------
# OpenAlex metadata helpers
# ---------------------------------------------------------------------------

_OPENALEX_SELECT = (
    "id,doi,display_name,authorships,publication_year,"
    "primary_location,biblio,abstract_inverted_index,"
    "keywords,ids,is_retracted,cited_by_count"
)


def _reconstruct_abstract(inverted_index: Optional[Dict[str, Any]]) -> Optional[str]:
    """Reconstruct plain-text abstract from OpenAlex inverted index format."""
    if not inverted_index:
        return None
    positions: Dict[int, str] = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    if not positions:
        return None
    return " ".join(positions[i] for i in sorted(positions))


def _parse_openalex_work(work: Dict[str, Any]) -> Dict[str, Any]:
    """Extract our metadata fields from a raw OpenAlex work dict."""
    result: Dict[str, Any] = {}

    # OpenAlex ID — bare (strip URL prefix)
    oa_id = work.get("id", "")
    if oa_id:
        result["openalex_id"] = oa_id.replace("https://openalex.org/", "").strip()

    # DOI — bare (strip URL prefix)
    doi_raw = work.get("doi") or ""
    if doi_raw:
        doi = doi_raw.replace("https://doi.org/", "").replace("http://doi.org/", "").lower().strip()
        if doi:
            result["doi"] = doi

    # Title
    title = (work.get("display_name") or "").strip()
    if title:
        result["title"] = title

    # Authors
    authorships = work.get("authorships") or []
    authors = [
        a["author"]["display_name"]
        for a in authorships
        if a.get("author", {}).get("display_name")
    ]
    if authors:
        result["authors"] = authors

    # Year
    year = work.get("publication_year")
    if year:
        try:
            result["year"] = int(year)
        except (TypeError, ValueError):
            pass

    # Journal
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    journal = (source.get("display_name") or "").strip()
    if journal:
        result["journal"] = journal

    # Biblio: volume, issue, pages
    biblio = work.get("biblio") or {}
    volume = (biblio.get("volume") or "").strip()
    if volume:
        result["volume"] = volume
    issue = (biblio.get("issue") or "").strip()
    if issue:
        result["issue"] = issue
    first_page = (biblio.get("first_page") or "").strip()
    last_page = (biblio.get("last_page") or "").strip()
    if first_page and last_page:
        result["pages"] = f"{first_page}-{last_page}"
    elif first_page:
        result["pages"] = first_page

    # Abstract
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    if abstract:
        result["abstract"] = abstract

    # Keywords
    kw_list = [kw.get("display_name", "").strip() for kw in (work.get("keywords") or [])]
    keywords = [k for k in kw_list if k]
    if keywords:
        result["keywords"] = keywords

    # Additional identifiers
    ids = work.get("ids") or {}
    pmid_raw = ids.get("pmid") or ""
    if pmid_raw:
        # pmid is typically "https://pubmed.ncbi.nlm.nih.gov/12345678"
        pmid = pmid_raw.strip().rstrip("/").rsplit("/", 1)[-1]
        if pmid.isdigit():
            result["pmid"] = pmid

    # Retraction flag and citation count
    result["is_retracted"] = bool(work.get("is_retracted", False))
    cited_by = work.get("cited_by_count")
    if cited_by is not None:
        try:
            result["cited_by_count"] = int(cited_by)
        except (TypeError, ValueError):
            pass

    return result


async def _openalex_lookup_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    """Fetch OpenAlex work record by exact DOI. Returns raw work dict or None."""
    import httpx

    params = {
        "filter": f"doi:{doi}",
        "select": _OPENALEX_SELECT,
        "mailto": settings.OPENALEX_EMAIL,
    }
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                resp = await client.get("https://api.openalex.org/works", params=params)
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code != 200:
                return None
            results = resp.json().get("results") or []
            return results[0] if results else None
        except Exception as exc:
            logger.debug("OpenAlex DOI lookup failed (attempt %d): %s", attempt + 1, exc)
            if attempt < 2:
                await asyncio.sleep(1)
    return None


async def _openalex_lookup_by_title(title: str, year: Optional[int]) -> Optional[Dict[str, Any]]:
    """Search OpenAlex by title, return best word-overlap match or None."""
    import httpx

    params: Dict[str, Any] = {
        "search": title,
        "select": _OPENALEX_SELECT,
        "per-page": 3,
        "mailto": settings.OPENALEX_EMAIL,
    }
    if year:
        params["filter"] = f"publication_year:{year - 1}-{year + 1}"

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                resp = await client.get("https://api.openalex.org/works", params=params)
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code != 200:
                return None
            results = resp.json().get("results") or []
            if not results:
                return None

            def _sim(work: Dict[str, Any]) -> float:
                oa_title = (work.get("display_name") or "").lower()
                qa = set(re.findall(r"\w+", title.lower()))
                qb = set(re.findall(r"\w+", oa_title))
                return len(qa & qb) / max(len(qa), len(qb), 1)

            best = max(results, key=_sim)
            return best if _sim(best) >= 0.35 else None
        except Exception as exc:
            logger.debug("OpenAlex title lookup failed (attempt %d): %s", attempt + 1, exc)
            if attempt < 2:
                await asyncio.sleep(1)
    return None


async def _identify_document_metadata(text: str, filename: str) -> Dict[str, Any]:
    """
    LLM agent that reads the opening pages of a document and extracts
    bibliographic metadata directly from the text.

    This runs *before* CrossRef / OpenAlex so that those APIs receive a
    proper title rather than a meaningless filename like 'Kooy2010_n.pdf'.

    Returns a dict with any subset of:
        title, authors (list[str]), year (int), journal, doi, isbn,
        publisher, abstract
    All values are best-effort; missing ones are simply absent.
    """
    import httpx
    import json as _json

    # Use the first ~6000 chars (title page + abstract + first paragraphs)
    # — enough to find all bibliographic metadata without wasting context.
    opening = text[:6000].strip()
    if not opening:
        return {}

    system = (
        "You are a bibliographic metadata extractor. "
        "Given the opening text of a scientific document, extract its bibliographic metadata. "
        "Return ONLY a single JSON object with these keys (omit any key you cannot determine with confidence):\n"
        "  title       — the full official title of the paper or book\n"
        "  authors     — array of author name strings (e.g. [\"Jane Smith\", \"John Doe\"])\n"
        "  year        — publication year as an integer\n"
        "  journal     — journal or book series name (papers) or publisher (books)\n"
        "  doi         — DOI string without the https://doi.org/ prefix\n"
        "  isbn        — ISBN string (books only)\n"
        "  abstract    — abstract text if present in the opening\n"
        "No markdown, no commentary, no extra keys — only the JSON object."
    )

    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": (
                f"Filename (for context only, do not use as title): {filename}\n\n"
                f"Opening text:\n\n{opening}"
            )},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{settings.OLLAMA_BASE_URL}/api/chat", json=payload)
            resp.raise_for_status()
            raw = resp.json()["message"]["content"].strip()

        # Strip <think>...</think> blocks from deepseek-r1
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        data = _json.loads(raw)
        if not isinstance(data, dict):
            return {}

        result: Dict[str, Any] = {}

        title = str(data.get("title") or "").strip()
        if title and len(title) > 4:
            result["title"] = title

        authors = data.get("authors")
        if isinstance(authors, list):
            cleaned = [str(a).strip() for a in authors if str(a).strip()]
            if cleaned:
                result["authors"] = cleaned
        elif isinstance(authors, str) and authors.strip():
            result["authors"] = [authors.strip()]

        year = data.get("year")
        if year is not None:
            try:
                y = int(year)
                if 1900 <= y <= 2100:
                    result["year"] = y
            except (TypeError, ValueError):
                pass

        for field in ("journal", "doi", "isbn", "abstract", "publisher"):
            val = str(data.get(field) or "").strip()
            if val:
                result[field] = val

        # Normalise DOI — strip URL prefix if present
        if "doi" in result:
            result["doi"] = (
                result["doi"]
                .replace("https://doi.org/", "")
                .replace("http://doi.org/", "")
                .lower()
                .strip()
            )

        logger.info(
            "_identify_document_metadata: title=%r year=%s doi=%s authors=%d",
            result.get("title"), result.get("year"), result.get("doi"),
            len(result.get("authors", [])),
        )
        return result

    except (_json.JSONDecodeError, ValueError) as exc:
        logger.debug("_identify_document_metadata: JSON parse failed: %s", exc)
        return {}
    except Exception as exc:
        logger.warning("_identify_document_metadata: failed: %s", exc)
        return {}


async def _enrich_metadata(filename: str, text: str = "") -> Dict[str, Any]:
    """
    Multi-source metadata enrichment pipeline:

    1. LLM agent — reads the opening text and identifies the true title,
       authors, year, journal/publisher, DOI, ISBN directly from the document.
    2. Filename parser — fills any gaps the LLM missed using Zotero-style
       filename patterns (Author - Year - Title).
    3. CrossRef — looks up the paper by title+year; provides DOI, canonical
       authors, references, abstract.
    4. OpenAlex — gap-fills keywords, volume/issue/pages, citation count,
       retraction flag, OpenAlex/PubMed IDs.

    Returns a dict with any subset of: title, doi, authors, year, journal,
    abstract, references, keywords, volume, issue, pages, isbn, openalex_id,
    pmid, cited_by_count, is_retracted.
    All values are best-effort; missing ones are simply omitted.
    """
    result: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Stage 1: LLM agent — ground truth from the document itself
    # ------------------------------------------------------------------
    if text:
        try:
            llm_meta = await _identify_document_metadata(text, filename)
            result.update(llm_meta)
        except Exception as exc:
            logger.warning("LLM metadata agent failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Stage 2: Filename parser — fill gaps LLM missed
    # ------------------------------------------------------------------
    parsed = _parse_pdf_filename(filename)
    year_parsed: Optional[int] = parsed.get("year")
    authors_raw: Optional[str] = parsed.get("authors_raw")
    paper_title: Optional[str] = parsed.get("paper_title")

    if not result.get("year") and year_parsed:
        result["year"] = year_parsed
    if not result.get("authors") and authors_raw:
        first = re.split(r"\s+(et al|e\.a\.|en |and |&)", authors_raw, flags=re.I)[0]
        first = first.strip().rstrip(",")
        if first:
            result["authors"] = [first]

    # Best title to use for API queries — prefer LLM result, fall back to filename
    query_title: Optional[str] = result.get("title") or paper_title
    query_year: Optional[int] = result.get("year") or year_parsed

    # ------------------------------------------------------------------
    # Stages 3 + 4: CrossRef and OpenAlex — run concurrently.
    #
    # CrossRef and OpenAlex are independent HTTP calls; there is no reason
    # to serialise them.  We fire both at the same time and merge results
    # once both settle.
    #
    # OpenAlex strategy: if the LLM already found a DOI we can query by
    # DOI directly; otherwise we query by title (same as before).  If
    # CrossRef later returns a DOI that OpenAlex missed we do a fast
    # follow-up DOI lookup, but only when the title-based result came back
    # empty to avoid an extra round trip in the common case.
    # ------------------------------------------------------------------

    cr_item: Optional[Dict[str, Any]] = None
    oa_work: Optional[Dict[str, Any]] = None

    if query_title:
        # Choose the OpenAlex starting query
        _oa_doi = result.get("doi")
        if _oa_doi:
            _oa_coro = _openalex_lookup_by_doi(_oa_doi)
        elif query_title:
            _oa_coro = _openalex_lookup_by_title(query_title, query_year)
        else:
            _oa_coro = asyncio.sleep(0)  # no-op

        try:
            cr_item, oa_work = await asyncio.gather(
                _crossref_lookup(query_title, query_year),
                _oa_coro,
                return_exceptions=True,
            )
            if isinstance(cr_item, Exception):
                logger.debug("CrossRef lookup failed: %s", cr_item)
                cr_item = None
            if isinstance(oa_work, Exception):
                logger.debug("OpenAlex lookup failed: %s", oa_work)
                oa_work = None
        except Exception as exc:
            logger.debug("Metadata API gather failed: %s", exc)
            cr_item = None
            oa_work = None

        # CrossRef result
        if cr_item:
            doi = (cr_item.get("DOI") or "").lower().strip()
            if doi and not result.get("doi"):
                result["doi"] = doi
            cr_authors = _parse_crossref_authors(cr_item)
            if cr_authors and not result.get("authors"):
                result["authors"] = cr_authors
            cr_year = _parse_crossref_year(cr_item)
            if cr_year and not result.get("year"):
                result["year"] = cr_year
            journal = _parse_crossref_journal(cr_item)
            if journal and not result.get("journal"):
                result["journal"] = journal
            abstract = _clean_crossref_abstract(cr_item.get("abstract"))
            if abstract and not result.get("abstract"):
                result["abstract"] = abstract
            ref_dois = [
                ref["DOI"].lower().strip()
                for ref in (cr_item.get("reference") or [])
                if ref.get("DOI")
            ]
            if ref_dois:
                result["references"] = ref_dois
            cr_title = ((cr_item.get("title") or [""])[0] or "").strip()
            if cr_title and not result.get("title"):
                result["title"] = cr_title

        # If OpenAlex title-search returned nothing but CrossRef gave us a
        # DOI, do a fast DOI-based follow-up (only when OpenAlex is empty).
        if oa_work is None and result.get("doi") and not _oa_doi:
            try:
                oa_work = await _openalex_lookup_by_doi(result["doi"])
            except Exception as exc:
                logger.debug("OpenAlex DOI follow-up failed: %s", exc)

    # OpenAlex result merge
    try:
        if oa_work and isinstance(oa_work, dict):
            oa = _parse_openalex_work(oa_work)
            for field in ("doi", "title", "authors", "year", "journal", "abstract"):
                if not result.get(field) and oa.get(field):
                    result[field] = oa[field]
            for field in ("keywords", "volume", "issue", "pages",
                          "openalex_id", "pmid", "cited_by_count", "is_retracted"):
                if oa.get(field) is not None:
                    result[field] = oa[field]
            oa_abstract = oa.get("abstract")
            if oa_abstract and len(oa_abstract) > len(result.get("abstract") or ""):
                result["abstract"] = oa_abstract
    except Exception as exc:
        logger.debug("OpenAlex merge failed: %s", exc)

    return result


async def _extract_facts(text: str) -> List[str]:
    """
    Extract scientific facts from a document by calling Ollama.

    For large documents (books, long reports) the text is split into sections
    of up to FACT_SECTION_CHARS characters with a small overlap, and each
    section is processed independently.  Facts are deduplicated by lowercased
    content before returning so overlapping sections don't produce duplicates.

    deepseek-r1 has a 131k-token context (~500k chars).  We use 80k-char
    sections to stay well within limits while covering the full document.
    """
    import httpx
    import json as _json

    # Section size in characters and overlap between consecutive sections.
    FACT_SECTION_CHARS = 80_000
    SECTION_OVERLAP    = 2_000

    model = settings.OLLAMA_MODEL
    system = (
        "You are a scientific fact extractor. "
        "Given text from a scientific document, return ONLY a JSON array of "
        "concise, self-contained factual statements drawn from the text. "
        "Focus on quantitative relationships, biological mechanisms, model "
        "parameters, experimental findings, and theoretical claims. "
        "Each element must be a plain string. "
        "No commentary, no markdown, no keys — just the JSON array."
    )

    def _parse_llm_facts(content: str) -> List[str]:
        """Parse LLM response into a list of fact strings."""
        clean = content.strip()
        # Strip <think>...</think> blocks produced by deepseek-r1
        import re as _re
        clean = _re.sub(r"<think>.*?</think>", "", clean, flags=_re.DOTALL).strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            parsed = _json.loads(clean)
            if isinstance(parsed, list):
                return [str(f).strip() for f in parsed if f and len(str(f).strip()) > 10]
        except (_json.JSONDecodeError, ValueError):
            pass
        # Fallback: extract lines that look like statements
        return [
            ln.lstrip("•-*0123456789. ").strip()
            for ln in content.splitlines()
            if len(ln.strip()) > 20
        ]

    # Build sections covering the entire text
    sections: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + FACT_SECTION_CHARS, len(text))
        sections.append(text[start:end])
        if end >= len(text):
            break
        start = end - SECTION_OVERLAP  # overlap with next section

    all_facts: List[str] = []
    seen_lower: set = set()

    for section_idx, section in enumerate(sections):
        if not section.strip():
            continue

        section_label = f"section {section_idx + 1}/{len(sections)}"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": (
                    f"Extract scientific facts from the following text "
                    f"({section_label}):\n\n{section}"
                )},
            ],
            "stream": False,
            "options": {"temperature": 0.2},
        }

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(f"{settings.OLLAMA_BASE_URL}/api/chat", json=payload)
                resp.raise_for_status()
                content = resp.json()["message"]["content"].strip()

            section_facts = _parse_llm_facts(content)
            for fact in section_facts:
                key = fact.lower()
                if key not in seen_lower:
                    seen_lower.add(key)
                    all_facts.append(fact)

            logger.info(
                "_extract_facts: %s → %d facts (running total %d)",
                section_label, len(section_facts), len(all_facts),
            )
        except Exception as exc:
            logger.warning("_extract_facts: %s failed: %s", section_label, exc)
            # Continue with remaining sections even if one fails

    return all_facts


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
        {"$set": {"status": batch_status, "updated_at": datetime.now(timezone.utc)}},
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
                      "updated_at": datetime.now(timezone.utc)}},
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

        # ---- Metadata enrichment (filename + CrossRef) -----------------
        filename_only = os.path.basename(source_path)
        try:
            meta = await _enrich_metadata(filename_only, text)
        except Exception as _meta_exc:
            logger.warning("Job %s: metadata enrichment failed (non-fatal): %s", job_id, _meta_exc)
            meta = {}

        # CrossRef references supersede regex-extracted ones when available
        enriched_references = meta.pop("references", None) or references

        document = Document(
            title=meta.get("title") or filename_only,
            doi=meta.get("doi"),
            authors=meta.get("authors") or [],
            year=meta.get("year"),
            journal=meta.get("journal"),
            abstract=meta.get("abstract"),
            source_type="pdf_local",
            source_path=job.source_path_or_url,
            content=text,
            general_domain=general_domain,
            processing_status="processing",
            references=enriched_references,
        )
        await db.documents.insert_one(document.model_dump(by_alias=True))
        logger.info(
            "Job %s: doi=%s authors=%d year=%s refs=%d",
            job_id, document.doi, len(document.authors), document.year, len(enriched_references),
        )
        await db.ingestion_jobs.update_one(
            {"_id": job.id},
            {"$set": {"document_id": document.id, "updated_at": datetime.now(timezone.utc)}},
        )

        # ---- Stage 2: fact extraction ----------------------------------
        if await _is_cancelled(db, batch_id_str):
            await _set_job_stage(db, job.id, "failed", status="cancelled",
                                 error_message="batch stopped by user")
            return

        await _set_job_stage(db, job.id, "fact_extraction", progress=30)
        fact_texts: List[str] = await _extract_facts(text)

        # Batch deduplication — one query for all fingerprints instead of N.
        fingerprints = [_fingerprint(ft) for ft in fact_texts]
        existing_map: Dict[str, Any] = {}
        async for doc in db.facts.find(
            {"content_fingerprint": {"$in": fingerprints}},
            {"_id": 1, "content_fingerprint": 1},
        ):
            existing_map[doc["content_fingerprint"]] = doc["_id"]

        now = datetime.now(timezone.utc)
        new_facts: List[Dict[str, Any]] = []
        fact_ids: List[Optional[ObjectId]] = []
        dup_fps: List[str] = []  # fingerprints of duplicates (for bulk update)

        for fact_text, fp in zip(fact_texts, fingerprints):
            if fp in existing_map:
                dup_fps.append(fp)
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
                new_facts.append(fact.model_dump(by_alias=True))
                fact_ids.append(fact.id)

        if new_facts:
            await db.facts.insert_many(new_facts, ordered=False)

        if dup_fps:
            await db.facts.update_many(
                {"content_fingerprint": {"$in": dup_fps}},
                {"$addToSet": {"additional_sources": document.id},
                 "$set": {"updated_at": now}},
            )

        await db.documents.update_one(
            {"_id": document.id},
            {"$set": {"processing_status": "completed", "updated_at": datetime.now(timezone.utc)}},
        )

        # ---- Stage 3: SF matching --------------------------------------
        if await _is_cancelled(db, batch_id_str):
            await _set_job_stage(db, job.id, "failed", status="cancelled",
                                 error_message="batch stopped by user")
            return

        await _set_job_stage(db, job.id, "sf_matching", progress=70)

        # Parallelize SF matching — each fact needs a keyword query + LLM
        # classification call.  Run them concurrently with a per-job semaphore
        # so we don't flood Ollama when many documents are ingested at once.
        _SF_SEM = asyncio.Semaphore(5)

        async def _bounded_match(fid: ObjectId, ftxt: str) -> List[Dict[str, Any]]:
            async with _SF_SEM:
                return await _match_sfs(db, fid, ftxt, general_domain)

        match_pairs = [(fid, ftxt) for fid, ftxt in zip(fact_ids, fact_texts) if fid is not None]
        match_results = await asyncio.gather(
            *[_bounded_match(fid, ftxt) for fid, ftxt in match_pairs],
            return_exceptions=True,
        )
        all_relations: List[Dict[str, Any]] = []
        for res in match_results:
            if isinstance(res, Exception):
                logger.warning("SF match task failed: %s", res)
            else:
                all_relations.extend(res)
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

                    now = datetime.now(timezone.utc)
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
                    await db.chunks.bulk_write(
                        [ReplaceOne({"chunk_id": cdoc["chunk_id"]}, cdoc, upsert=True)
                         for cdoc in chunk_docs],
                        ordered=False,
                    )

                    chunk_count = len(chunks)
                    await db.documents.update_one(
                        {"_id": document.id},
                        {"$set": {
                            "embedding_status": "embedded",
                            "num_chunks": chunk_count,
                            "updated_at": datetime.now(timezone.utc),
                        }},
                    )
                    logger.info("Job %s: embedded %d chunks into ChromaDB", job_id, chunk_count)
            except Exception as embed_exc:
                logger.warning("Job %s: embedding failed (non-fatal): %s", job_id, embed_exc)
                await db.documents.update_one(
                    {"_id": document.id},
                    {"$set": {"embedding_status": "failed", "updated_at": datetime.now(timezone.utc)}},
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
    db,  # ArangoDatabase
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
    db,  # ArangoDatabase
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
