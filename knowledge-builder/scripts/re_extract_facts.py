"""
Re-run fact extraction for documents that have content but zero facts.

Uses the same Ollama-based extraction as pipeline.py.

Usage:
    # Dry-run: show which docs would be processed
    conda run -n advandeb python scripts/re_extract_facts.py --dry-run --limit 10

    # Real run
    conda run -n advandeb python scripts/re_extract_facts.py

    # With concurrency limit and timeout adjustment
    conda run -n advandeb python scripts/re_extract_facts.py --concurrency 2 --timeout 300

    # Force re-extract even docs that already have facts
    conda run -n advandeb python scripts/re_extract_facts.py --force
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SEM: asyncio.Semaphore


# ---------------------------------------------------------------------------
# Fact extraction (mirrors pipeline.py)
# ---------------------------------------------------------------------------

async def _extract_facts(text: str, timeout: float = 240.0) -> List[str]:
    """Call Ollama to extract facts from text. Returns list of fact strings."""
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

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{settings.OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()
        content = resp.json()["message"]["content"].strip()

    # Parse JSON array
    try:
        clean = content
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        facts = json.loads(clean)
        if isinstance(facts, list):
            return [str(f) for f in facts if f]
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: line splitting
    facts = [
        ln.lstrip("•-*0123456789. ").strip()
        for ln in content.splitlines()
        if len(ln.strip()) > 20
    ]
    return facts[:20]


async def _match_stylized_facts(
    db: Any,
    fact_id: ObjectId,
    fact_content: str,
) -> int:
    """Match a fact against stylized facts. Returns number of matches written."""
    try:
        sf_count = await db.stylized_facts.count_documents({})
        if sf_count == 0:
            return 0

        cursor = db.stylized_facts.find(
            {},
            {"statement": 1, "category": 1, "sf_number": 1},
        )
        sfs = await cursor.to_list(length=200)

        model = settings.OLLAMA_MODEL
        sf_summaries = "\n".join(
            f"[{sf.get('sf_number','?')}] {sf['statement']}" for sf in sfs[:50]
        )
        system = (
            "You are a scientific knowledge linker. "
            "Given a fact and a list of stylized facts, return ONLY a JSON array of objects "
            "with 'sf_id' (string), 'relation_type' ('supports'/'opposes'), 'confidence' (0-1). "
            "Return [] if nothing matches well."
        )
        prompt = (
            f"Fact: {fact_content}\n\n"
            f"Stylized facts:\n{sf_summaries}\n\n"
            "Which stylized facts does this fact support or oppose?"
        )

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{settings.OLLAMA_BASE_URL}/api/chat", json=payload)
            resp.raise_for_status()
            content = resp.json()["message"]["content"].strip()

        matches = []
        try:
            clean = content
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            matches = json.loads(clean)
            if not isinstance(matches, list):
                matches = []
        except (json.JSONDecodeError, ValueError):
            pass

        written = 0
        for m in matches[:10]:
            if not isinstance(m, dict):
                continue
            sf_num = str(m.get("sf_id", "")).strip()
            if not sf_num:
                continue
            sf_doc = next((s for s in sfs if str(s.get("sf_number")) == sf_num), None)
            if sf_doc is None:
                continue

            rel = {
                "fact_id": fact_id,
                "sf_id": sf_doc["_id"],
                "relation_type": m.get("relation_type", "supports"),
                "confidence": float(m.get("confidence", 0.5)),
                "status": "suggested",
                "created_at": datetime.utcnow(),
            }
            await db.fact_sf_relations.insert_one(rel)
            written += 1

        return written
    except Exception as e:
        logger.debug("SF matching failed for fact %s: %s", fact_id, e)
        return 0


# ---------------------------------------------------------------------------
# Per-document processing
# ---------------------------------------------------------------------------


async def process_one(
    doc: Dict[str, Any],
    db: Any,
    dry_run: bool,
    timeout: float,
    skip_sf_matching: bool,
) -> Tuple[str, str, int]:
    """
    Extract facts for one document.
    Returns (doc_id, status, facts_added).
    Status: 'done', 'no_content', 'error', 'dry_run'
    """
    doc_id = doc["_id"]
    title = doc.get("title", "?")[:60]
    content: str = doc.get("content") or ""

    if len(content) < 100:
        return str(doc_id), "no_content", 0

    async with SEM:
        try:
            fact_texts = await _extract_facts(content, timeout=timeout)
        except Exception as e:
            logger.warning("Fact extraction failed for %s: %s", title, e)
            return str(doc_id), "error", 0

    if not fact_texts:
        return str(doc_id), "done", 0

    if dry_run:
        logger.info("DRY-RUN %s: would add %d facts", title, len(fact_texts))
        return str(doc_id), "dry_run", len(fact_texts)

    # Insert facts
    now = datetime.utcnow()
    fact_docs = [
        {
            "content": ft,
            "document_id": doc_id,
            "page_number": None,
            "entities": [],
            "tags": [],
            "general_domain": doc.get("general_domain"),
            "confidence": 0.8,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        for ft in fact_texts
    ]
    result = await db.facts.insert_many(fact_docs)
    inserted_ids = result.inserted_ids

    # Update num_facts on document
    await db.documents.update_one(
        {"_id": doc_id},
        {"$set": {"num_facts": len(fact_texts), "updated_at": now}},
    )

    # SF matching (optional, can be slow)
    sf_matches = 0
    if not skip_sf_matching:
        for fact_id, fact_text in zip(inserted_ids, fact_texts):
            sf_matches += await _match_stylized_facts(db, fact_id, fact_text)

    logger.debug(
        "  %s: +%d facts, %d SF matches", title, len(fact_texts), sf_matches
    )
    return str(doc_id), "done", len(fact_texts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(
    limit: int,
    concurrency: int,
    dry_run: bool,
    force: bool,
    timeout: float,
    skip_sf_matching: bool,
    mongodb_url: str,
    db_name: str,
) -> None:
    global SEM
    SEM = asyncio.Semaphore(concurrency)

    client = AsyncIOMotorClient(mongodb_url)
    db = client[db_name]

    query: Dict[str, Any] = {"source_type": "pdf_local"}
    if not force:
        query["num_facts"] = 0

    total = await db.documents.count_documents(query)
    logger.info(
        "Found %d documents needing fact extraction (limit=%d force=%s)",
        total, limit, force,
    )

    cursor = db.documents.find(query, limit=limit or 0)
    docs = await cursor.to_list(length=limit or total)

    counts = {"done": 0, "no_content": 0, "error": 0, "dry_run": 0}
    total_facts = 0
    start = time.time()

    tasks = [
        process_one(doc, db, dry_run, timeout, skip_sf_matching)
        for doc in docs
    ]

    done = 0
    for coro in asyncio.as_completed(tasks):
        doc_id, status, n_facts = await coro
        counts[status] = counts.get(status, 0) + 1
        total_facts += n_facts
        done += 1
        if done % 20 == 0 or done == len(docs):
            elapsed = time.time() - start
            rate = done / elapsed if elapsed > 0 else 0
            logger.info(
                "  Progress: %d/%d (%.1f docs/s) done=%d no_content=%d errors=%d facts=%d",
                done, len(docs), rate,
                counts["done"], counts["no_content"], counts["error"], total_facts,
            )

    elapsed = time.time() - start
    logger.info(
        "Finished in %.1fs — done=%d no_content=%d error=%d facts_added=%d",
        elapsed, counts["done"], counts["no_content"], counts["error"], total_facts,
    )
    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-extract facts for pdf_local docs with zero facts"
    )
    parser.add_argument("--limit", type=int, default=0, help="Max docs (0=all)")
    parser.add_argument("--concurrency", type=int, default=2, help="Parallel Ollama calls")
    parser.add_argument("--timeout", type=float, default=240.0, help="Ollama timeout seconds")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--force", action="store_true", help="Re-extract even docs with facts")
    parser.add_argument("--skip-sf-matching", action="store_true", help="Skip SF matching (faster)")
    parser.add_argument("--mongodb-url", default="mongodb://localhost:27017")
    parser.add_argument("--db-name", default="advandeb")
    args = parser.parse_args()

    asyncio.run(
        run(
            limit=args.limit,
            concurrency=args.concurrency,
            dry_run=args.dry_run,
            force=args.force,
            timeout=args.timeout,
            skip_sf_matching=args.skip_sf_matching,
            mongodb_url=args.mongodb_url,
            db_name=args.db_name,
        )
    )


if __name__ == "__main__":
    main()
