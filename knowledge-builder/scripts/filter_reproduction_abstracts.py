"""
Two-stage domain-relevance filter for ``deb_abstracts_reproduction.abstracts``.

WHY: this collection is 4.55M abstracts bulk-imported from OpenAlex by
searching the bare keyword "reproduction" — a term that spans animal biology,
human obstetric medicine, sociology, gender studies, and literary criticism.
The stored schema (doc_id/openalex_id/doi/title/year/abstract) never kept
OpenAlex's own concept/topic tags, so there's no cheap authoritative signal
to filter on. A manual sample (5000 random docs) showed ~8% clear off-domain
titles (human clinical case reports, sociology, gender studies, literary
criticism) — the true rate is likely higher since many human-medicine papers
don't trip an obvious keyword.

DESIGN — two stages, deliberately asymmetric:
  Stage 1 (fast, local, no LLM): a broad off-domain keyword/phrase blocklist
      over title+abstract. Deliberately HIGH RECALL / LOW PRECISION — e.g. it
      will flag "Metabolism of sheep adipose tissue during pregnancy" (a
      legitimate animal study) purely because it contains "pregnan". That's
      fine: stage 1 only *shortlists* candidates for review, nothing is
      excluded on stage-1 evidence alone.
  Stage 2 (LLM confirm): only the stage-1-shortlisted subset gets a real
      judgment via the SAME classifier the live ingestion pipeline uses
      (app.kb.pipeline._classify_domain_relevance) — title+abstract, one
      cheap local Ollama call, fails OPEN (defaults to relevant) on any error
      so a transient failure can never wrongly exclude a real paper.

NON-DESTRUCTIVE: this script only tags documents — flagged_stage1,
stage1_checked, is_relevant, exclusion_reason, reviewed_at. Nothing is
deleted. Review the --report counts, then decide separately whether/how to
exclude or physically remove confirmed off-domain records and their
abstract_chunks (joined by doc_id).

IDEMPOTENT + RESUMABLE: stage 1 only touches docs missing stage1_checked;
stage 2 only touches flagged docs missing reviewed_at. Safe to Ctrl-C and
restart.

Usage:
    # Stage 1 — tag candidates via keyword blocklist (fast, minutes)
    conda run -n advandeb python knowledge-builder/scripts/filter_reproduction_abstracts.py --stage1

    # Stage 2 — LLM-confirm the stage-1 shortlist (slow — run in background)
    nohup conda run -n advandeb python knowledge-builder/scripts/filter_reproduction_abstracts.py --stage2 \
        > /tmp/repro_filter_stage2.log 2>&1 &

    # Report current tag counts without doing anything
    conda run -n advandeb python knowledge-builder/scripts/filter_reproduction_abstracts.py --report
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running from repo root; reuse the live pipeline's domain-relevance
# classifier (title+abstract → is_relevant, reason) instead of a second copy.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "backend"))

from motor.motor_asyncio import AsyncIOMotorClient

from app.kb.pipeline import _classify_domain_relevance  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("filter_reproduction_abstracts")

DB_NAME = "deb_abstracts_reproduction"

# ---------------------------------------------------------------------------
# Stage 1 — broad, high-recall keyword/phrase blocklist.
# Grouped by category purely for readability; matched as one alternation.
# ---------------------------------------------------------------------------
_STAGE1_TERMS = [
    # Religion / theology
    r"religio\w*", r"theolog\w*", r"scripture", r"christian\w*", r"islam\w*",
    r"muslim", r"buddhis\w*", r"hindu\w*", r"catholic\w*", r"\bchurch\b", r"spiritual\w*",
    # Politics / government policy (pure human governance, no ecology angle)
    r"\belection\w*", r"\bparliament\w*", r"\bvoter\w*", r"\bcongress\b",
    r"\bpresident\w*", r"\blegislat\w*",
    # Human social science / humanities
    r"sociolog\w*", r"anthropolog\w*", r"\bgender\b", r"feminis\w*", r"patriarch\w*",
    r"\bliterary\b", r"\bnovel\b", r"\bfiction\b", r"\bpoetry\b", r"\bfilm\b",
    r"\btelevision\b",
    # Human clinical medicine (leaks in via bare "reproduction" search)
    r"\bpatients?\b", r"clinical trial", r"randomized controlled trial",
    r"\bhospital\b", r"case report", r"\bcohort study\b", r"\bsurgery\b",
    r"\bcancer\b", r"oncolog\w*", r"psychiatr\w*",
    # Human reproduction / demography specifics
    r"family planning", r"fertility rate", r"reproductive rights", r"abortion",
    r"contracepti\w*", r"in vitro fertili\w*", r"\bivf\b",
    r"assisted reproductive technology", r"\bmenopause\b",
]
_STAGE1_RE = re.compile("|".join(_STAGE1_TERMS), re.IGNORECASE)

# ---------------------------------------------------------------------------
# Stage 2 pre-check — biological/organism vocabulary allow-list.
# Broad, high-recall on purpose: this only decides whether a stage-1-flagged
# record is even AMBIGUOUS enough to deserve an LLM call. If it hits zero of
# these terms, it has no biological signal at all (pure politics/sociology/
# religion/humanities/unrelated-tech) and is auto-excluded without spending an
# Ollama call. If it hits any, the case is ambiguous (e.g. "human ovary" also
# matches "ovary") and goes to the LLM for the real judgment call.
# ---------------------------------------------------------------------------
_BIO_TERM_TERMS = [
    r"organism\w*", r"\bspecies\b", r"\bgenus\b", r"\btaxon\w*", r"wildlife",
    r"\banimal\w*", r"\bplant\w*", r"vertebrate\w*", r"invertebrate\w*",
    r"\bmammal\w*", r"\bfish\b", r"\bfishes\b", r"\bbird\w*", r"reptile\w*",
    r"amphibian\w*", r"\binsect\w*", r"mollus[ck]\w*", r"crustacean\w*",
    r"bacteri\w*", r"\bfungu?[si]\b", r"\bmicrobe\w*", r"\bmicrobial\b",
    r"biolog\w*", r"physiolog\w*", r"metabol\w*", r"ecolog\w*", r"zoolog\w*",
    r"botan\w*", r"genom\w*", r"genetic\w*", r"phylogen\w*", r"evolutio\w*",
    r"morpholog\w*", r"anatom\w*", r"biochem\w*", r"endocrin\w*",
    r"microbiolog\w*", r"\bcells?\b", r"\btissues?\b", r"\benzymes?\b",
    r"\bproteins?\b", r"\bhormones?\b", r"\breceptors?\b", r"\bchromosome\w*",
    r"\bhabitat\w*", r"\becosystem\w*", r"\bpopulation\w*", r"\boffspring\b",
    r"\blarva\w*", r"\bembryo\w*", r"\bgestation\b", r"\bDEB\b",
    r"dynamic energy budget", r"bioenerg\w*", r"assimilat\w*",
]
_BIO_TERM_RE = re.compile("|".join(_BIO_TERM_TERMS), re.IGNORECASE)


async def run_stage1(db, batch_size: int, limit: int) -> None:
    """Tag every un-checked abstract with stage1_checked + flagged_stage1."""
    await db.abstracts.create_index("doc_id")
    query = {"stage1_checked": {"$ne": True}}
    total = await db.abstracts.count_documents(query)
    logger.info("Stage 1: %d abstracts not yet checked (limit=%d)", total, limit)

    cursor = db.abstracts.find(
        query, {"title": 1, "abstract": 1}, no_cursor_timeout=True, batch_size=batch_size
    )
    if limit:
        cursor = cursor.limit(limit)

    from pymongo import UpdateOne

    checked = 0
    flagged = 0
    ops: List[UpdateOne] = []
    start = time.time()

    async for doc in cursor:
        text = f"{doc.get('title') or ''} {doc.get('abstract') or ''}"
        is_flagged = bool(_STAGE1_RE.search(text))
        ops.append(UpdateOne(
            {"_id": doc["_id"]},
            {"$set": {"stage1_checked": True, "flagged_stage1": is_flagged}},
        ))
        checked += 1
        flagged += int(is_flagged)

        if len(ops) >= 2000:
            await db.abstracts.bulk_write(ops, ordered=False)
            ops = []
            elapsed = time.time() - start
            logger.info(
                "  Stage 1: %d/%d checked (%.0f/s) — %d flagged so far",
                checked, total, checked / max(elapsed, 0.001), flagged,
            )

    if ops:
        await db.abstracts.bulk_write(ops, ordered=False)

    logger.info(
        "Stage 1 done: %d checked, %d flagged (%.1f%%) in %.0fs",
        checked, flagged, 100 * flagged / max(checked, 1), time.time() - start,
    )


async def run_stage2(db, concurrency: int, limit: int, dry_run: bool, model: Optional[str]) -> None:
    """LLM-confirm the stage-1 shortlist. Only touches flagged, unreviewed docs."""
    query = {"flagged_stage1": True, "reviewed_at": {"$exists": False}}
    total = await db.abstracts.count_documents(query)
    logger.info(
        "Stage 2: %d flagged abstracts awaiting LLM review (limit=%d, dry_run=%s, model=%s)",
        total, limit, dry_run, model or "default",
    )

    cursor = db.abstracts.find(
        query, {"title": 1, "abstract": 1}, no_cursor_timeout=True
    )
    if limit:
        cursor = cursor.limit(limit)
    docs = await cursor.to_list(length=limit or total)

    sem = asyncio.Semaphore(concurrency)
    counts = {"relevant": 0, "excluded": 0, "error": 0, "auto_excluded_no_bio_terms": 0}
    start = time.time()

    async def _review(doc: Dict[str, Any]) -> None:
        title = doc.get("title") or ""
        abstract = doc.get("abstract") or ""
        text = f"{title} {abstract}"

        # Cheap pre-check (no semaphore, no Ollama call): a stage-1-flagged
        # record with ZERO biological/organism vocabulary anywhere in its
        # title+abstract is unambiguous — pure politics/sociology/religion/
        # humanities/unrelated-tech — and doesn't need an LLM judgment.
        if not _BIO_TERM_RE.search(text):
            is_relevant, reason = False, "no biological/organism terms found — auto-excluded without LLM call"
            counts["auto_excluded_no_bio_terms"] += 1
            counts["excluded"] += 1
        else:
            async with sem:
                try:
                    is_relevant, reason = await _classify_domain_relevance(title, abstract, model=model)
                except Exception as exc:  # belt-and-suspenders — classifier already fails open
                    logger.warning("Stage 2: classification error for %s: %s", doc["_id"], exc)
                    is_relevant, reason = True, f"classification error: {exc}"
                    counts["error"] += 1
                counts["relevant" if is_relevant else "excluded"] += 1

        if not dry_run:
            await db.abstracts.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "is_relevant": is_relevant,
                    "exclusion_reason": None if is_relevant else reason,
                    "reviewed_at": datetime.now(timezone.utc),
                }},
            )

    done = 0
    tasks = [_review(d) for d in docs]
    for coro in asyncio.as_completed(tasks):
        await coro
        done += 1
        if done % 100 == 0 or done == len(docs):
            elapsed = time.time() - start
            logger.info(
                "  Stage 2: %d/%d reviewed (%.2f/s) — relevant=%d excluded=%d "
                "(%d auto, no-LLM) errors=%d",
                done, len(docs), done / max(elapsed, 0.001),
                counts["relevant"], counts["excluded"],
                counts["auto_excluded_no_bio_terms"], counts["error"],
            )

    logger.info(
        "Stage 2 done: relevant=%d excluded=%d (%d auto-excluded without an LLM call) errors=%d in %.0fs",
        counts["relevant"], counts["excluded"], counts["auto_excluded_no_bio_terms"],
        counts["error"], time.time() - start,
    )


async def run_report(db) -> None:
    total = await db.abstracts.count_documents({})
    checked = await db.abstracts.count_documents({"stage1_checked": True})
    flagged = await db.abstracts.count_documents({"flagged_stage1": True})
    reviewed = await db.abstracts.count_documents({"reviewed_at": {"$exists": True}})
    excluded = await db.abstracts.count_documents({"is_relevant": False})
    confirmed_relevant = await db.abstracts.count_documents({"is_relevant": True})

    print(f"Total abstracts:              {total:,}")
    print(f"Stage 1 checked:               {checked:,} ({100*checked/max(total,1):.1f}%)")
    print(f"Stage 1 flagged (shortlist):   {flagged:,} ({100*flagged/max(checked,1):.1f}% of checked)")
    print(f"Stage 2 reviewed by LLM:       {reviewed:,} ({100*reviewed/max(flagged,1):.1f}% of flagged)")
    print(f"  confirmed off-domain:        {excluded:,}")
    print(f"  confirmed relevant:          {confirmed_relevant:,}")
    if excluded:
        print("\nSample confirmed off-domain titles:")
        async for doc in db.abstracts.find(
            {"is_relevant": False}, {"title": 1, "exclusion_reason": 1}
        ).limit(15):
            print(f"  - {doc.get('title', '')[:90]}  [{doc.get('exclusion_reason', '')[:60]}]")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1", action="store_true", help="Run stage 1 (keyword shortlist)")
    parser.add_argument("--stage2", action="store_true", help="Run stage 2 (LLM confirm shortlist)")
    parser.add_argument("--report", action="store_true", help="Print current tag counts")
    parser.add_argument("--limit", type=int, default=0, help="Max docs to process (0 = all)")
    parser.add_argument("--batch-size", type=int, default=5000, help="Stage 1 cursor batch size")
    parser.add_argument("--concurrency", type=int, default=4, help="Stage 2 parallel Ollama calls")
    parser.add_argument("--dry-run", action="store_true", help="Stage 2: classify but don't write")
    parser.add_argument(
        "--model", default=None,
        help="Ollama model for stage 2 (default: settings.OLLAMA_MODEL). "
             "This is a simple binary judgment — a small/fast model (e.g. gemma2:2b) "
             "is recommended for a corpus this large.",
    )
    parser.add_argument("--mongodb-url", default="mongodb://localhost:27017")
    args = parser.parse_args()

    if not (args.stage1 or args.stage2 or args.report):
        parser.error("Specify one of --stage1, --stage2, --report")

    client = AsyncIOMotorClient(args.mongodb_url)
    db = client[DB_NAME]

    async def _main():
        if args.stage1:
            await run_stage1(db, args.batch_size, args.limit)
        if args.stage2:
            await run_stage2(db, args.concurrency, args.limit, args.dry_run, args.model)
        if args.report:
            await run_report(db)

    asyncio.run(_main())
    client.close()


if __name__ == "__main__":
    main()
