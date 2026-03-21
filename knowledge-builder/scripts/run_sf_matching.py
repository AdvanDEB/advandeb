"""
run_sf_matching.py — Run SF matching via Ollama LLM for all unmatched facts.

Skips facts that already have at least one entry in fact_sf_relations.
Logs progress every 100 facts.

Usage:
    DATABASE_NAME=advandeb conda run -n advandeb python scripts/run_sf_matching.py
    DATABASE_NAME=advandeb conda run -n advandeb python scripts/run_sf_matching.py --concurrency 2 --limit 500
"""

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, List

import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from advandeb_kb.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("sf_match")

SEM: asyncio.Semaphore = asyncio.Semaphore(1)


async def _load_stylized_facts(db: Any) -> List[dict]:
    cursor = db.stylized_facts.find({}, {"statement": 1, "category": 1, "sf_number": 1})
    return await cursor.to_list(length=500)


async def _match_one(
    db: Any,
    sfs: List[dict],
    fact_id: ObjectId,
    fact_content: str,
) -> int:
    """Match one fact against stylized facts via Ollama. Returns # relations written."""
    try:
        sf_summaries = "\n".join(
            f"[{sf.get('sf_number', '?')}] {sf['statement']}" for sf in sfs[:50]
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
            "model": settings.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }

        async with SEM:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat", json=payload
                )
                resp.raise_for_status()
                raw = resp.json()["message"]["content"].strip()

        matches = []
        try:
            clean = raw
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
                "created_by": "agent",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
            await db.fact_sf_relations.insert_one(rel)
            written += 1

        return written
    except Exception as e:
        logger.debug("SF match failed for fact %s: %s", fact_id, e)
        return 0


async def run(
    concurrency: int,
    limit: int,
    dry_run: bool,
    mongodb_url: str,
    db_name: str,
) -> None:
    global SEM
    SEM = asyncio.Semaphore(concurrency)

    client = AsyncIOMotorClient(mongodb_url)
    db = client[db_name]

    # Load stylized facts once
    sfs = await _load_stylized_facts(db)
    logger.info("Loaded %d stylized facts", len(sfs))
    if not sfs:
        logger.error("No stylized facts found — aborting")
        return

    # Ensure index on fact_id for fast per-fact lookups
    await db.fact_sf_relations.create_index("fact_id")
    logger.info("Index on fact_sf_relations.fact_id ensured")

    total_facts = await db.facts.count_documents({})
    logger.info("Total facts in DB: %d — will stream and skip already-matched ones", total_facts)

    if dry_run:
        logger.info("DRY-RUN mode — exiting without processing")
        return

    total_written = 0
    processed = 0
    skipped = 0
    start = time.time()

    # Paginate by _id to avoid cursor timeout (LLM calls take ~13s each, cursor expires in 10 min)
    PAGE_SIZE = 100
    last_id = None
    done = False

    while not done:
        query = {}
        if last_id is not None:
            query["_id"] = {"$gt": last_id}
        page = await db.facts.find(query, {"content": 1}).sort("_id", 1).limit(PAGE_SIZE).to_list(length=PAGE_SIZE)
        if not page:
            break

        for fact in page:
            fact_id = fact["_id"]
            last_id = fact_id

            # Skip if already has at least one SF relation
            existing = await db.fact_sf_relations.count_documents({"fact_id": fact_id}, limit=1)
            if existing:
                skipped += 1
                continue

            written = await _match_one(db, sfs, fact_id, fact.get("content", ""))
            total_written += written
            processed += 1

            if limit and processed >= limit:
                logger.info("Reached limit of %d facts — stopping", limit)
                done = True
                break

            if processed % 100 == 0:
                elapsed = time.time() - start
                rate = processed / elapsed if elapsed > 0 else 0
                checked = processed + skipped
                remaining_est = (total_facts - checked) / rate if rate > 0 else 0
                logger.info(
                    "Progress: checked=%d processed=%d skipped=%d rate=%.2f/s relations=%d ETA=%.0f min",
                    checked, processed, skipped, rate, total_written, remaining_est / 60,
                )

    logger.info(
        "Done — processed %d facts (skipped %d already matched), wrote %d SF relations in %.1f min",
        processed, skipped, total_written, (time.time() - start) / 60,
    )
    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SF matching for unmatched facts")
    parser.add_argument("--concurrency", type=int, default=1, help="Ollama call concurrency")
    parser.add_argument("--limit", type=int, default=0, help="Max facts to process (0=all)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mongodb-url", default=settings.MONGODB_URL)
    parser.add_argument("--db-name", default=settings.DATABASE_NAME)
    args = parser.parse_args()

    asyncio.run(
        run(
            concurrency=args.concurrency,
            limit=args.limit,
            dry_run=args.dry_run,
            mongodb_url=args.mongodb_url,
            db_name=args.db_name,
        )
    )


if __name__ == "__main__":
    main()
