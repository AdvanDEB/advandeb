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

THE STAGE-1 GAP: the blocklist only knows off-domain *topics*, but most of
the pollution comes from other *senses* of the word "reproduction" — the basic
reproduction number R0, reproducibility, image/colour reproduction, "social
reproduction", reproduced numerical models. None of those trip stage 1, so a
random sample of unflagged abstracts that reached the KB still ran ~15%
off-domain. ``--scope facts`` / ``--scope in-kb`` therefore send *unflagged*
abstracts to the LLM too, limited to the ones that actually reached the KB
(produced facts, or were embedded for chat retrieval).

GATE VERSIONS: verdicts carry the classifier's ``review_version``
(app.kb.pipeline.DOMAIN_GATE_VERSION). An off-domain verdict stands once made,
but a "relevant" verdict from an older, more lenient prompt counts as
unreviewed — stage 2 re-judges it, and propagate doesn't treat it as vetted.

STAGES 1-2 ONLY TAG Mongo — flagged_stage1, stage1_checked, is_relevant,
exclusion_reason, review_reason, review_version, reviewed_at. ``--propagate`` is the step that
acts on the verdicts in the canonical stores (ArangoDB + ChromaDB):
  - every judged document gets ``is_relevant`` copied onto its Arango record;
  - off-domain documents are KEPT as auditable records with
    processing_status="excluded" + exclusion_reason, while everything derived
    from them — facts, chunks, chunk vectors, and the graph edges that make the
    document reachable (taxon/topic/author/citation links) — is deleted.
    All of that is regenerable: to overturn a verdict, set the document back to
    pending and re-run extraction/embedding.

IDEMPOTENT + RESUMABLE: stage 1 only touches docs missing stage1_checked;
stage 2 only touches docs without a current verdict, and never records one
when the classifier itself failed (it fails open, and persisting that as
"relevant" would hide the doc from every later pass). Propagate re-applies
cleanly. Safe to Ctrl-C and restart any stage.

Usage:
    # Stage 1 — tag candidates via keyword blocklist (fast, minutes)
    conda run -n advandeb python knowledge-builder/scripts/filter_reproduction_abstracts.py --stage1

    # Stage 2 — LLM-confirm the stage-1 shortlist (slow — run in background)
    nohup conda run -n advandeb python knowledge-builder/scripts/filter_reproduction_abstracts.py --stage2 \
        > /tmp/repro_filter_stage2.log 2>&1 &

    # Stage 2 over every abstract that produced facts and lacks a current verdict
    # (``--scope in-kb`` also covers the ones embedded for chat retrieval)
    conda run -n advandeb python knowledge-builder/scripts/filter_reproduction_abstracts.py --stage2 --scope facts

    # Apply verdicts to ArangoDB + ChromaDB (preview first with --dry-run)
    conda run -n advandeb python knowledge-builder/scripts/filter_reproduction_abstracts.py --propagate --dry-run

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
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

# Allow running from repo root; reuse the live pipeline's domain-relevance
# classifier (title+abstract → is_relevant, reason) instead of a second copy.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "backend"))

from motor.motor_asyncio import AsyncIOMotorClient

from app.kb.pipeline import (  # noqa: E402
    DOMAIN_GATE_FAILED_REASON,
    DOMAIN_GATE_VERSION,
    _classify_domain_relevance,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("filter_reproduction_abstracts")
logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per Ollama call otherwise

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


def _arango():
    from advandeb_kb.database.arango_client import ArangoDatabase

    a = ArangoDatabase()
    a.connect()
    return a


def _in_kb_keys(scope: str) -> List[str]:
    """Keys of reproduction abstracts that reached the KB: produced facts
    (``facts``) or, for ``in-kb``, also embedded for chat retrieval."""
    embedded = "OR d.embedding_status == 'embedded'" if scope == "in-kb" else ""
    return _arango().aql(
        "FOR d IN documents FILTER d.general_domain == 'reproduction' "
        f"AND (d.processing_status == 'completed' {embedded}) RETURN d._key"
    )


async def _stage2_batches(
    db, scope: str, batch_size: int, limit: int
) -> AsyncIterator[List[Dict[str, Any]]]:
    """Yield batches of abstracts lacking a current verdict, one record per
    doc_id (the collection holds duplicate imports; the verdict is written to
    every copy)."""
    projection = {"doc_id": 1, "title": 1, "abstract": 1, "flagged_stage1": 1}
    unreviewed = {"is_relevant": {"$ne": False}, "review_version": {"$ne": DOMAIN_GATE_VERSION}}
    yielded = 0

    if scope == "flagged":
        sources: List[Dict[str, Any]] = [{"flagged_stage1": True, **unreviewed}]
    else:
        keys = _in_kb_keys(scope)
        logger.info("Stage 2 (%s): %d abstracts in the KB to check", scope, len(keys))
        sources = [
            {"doc_id": {"$in": keys[i:i + batch_size]}, **unreviewed}
            for i in range(0, len(keys), batch_size)
        ]

    seen: set = set()
    batch: List[Dict[str, Any]] = []
    for query in sources:
        async for doc in db.abstracts.find(query, projection, no_cursor_timeout=True):
            if doc.get("doc_id") in seen:
                continue
            seen.add(doc.get("doc_id"))
            batch.append(doc)
            if len(batch) >= batch_size or (limit and yielded + len(batch) >= limit):
                yield batch
                yielded += len(batch)
                batch = []
                if limit and yielded >= limit:
                    return
    if batch:
        yield batch


async def run_stage2(
    db, scope: str, concurrency: int, batch_size: int, limit: int,
    dry_run: bool, model: Optional[str],
) -> None:
    """LLM-review unreviewed abstracts in ``scope`` and tag every copy."""
    logger.info(
        "Stage 2: scope=%s limit=%d dry_run=%s model=%s",
        scope, limit, dry_run, model or "default",
    )
    sem = asyncio.Semaphore(concurrency)
    counts = {"relevant": 0, "excluded": 0, "error": 0, "auto_excluded_no_bio_terms": 0}
    done = 0
    start = time.time()

    async def _review(doc: Dict[str, Any]) -> None:
        title = doc.get("title") or ""
        abstract = doc.get("abstract") or ""
        text = f"{title} {abstract}"

        # Cheap pre-check (no Ollama call): a record that tripped the stage-1
        # off-domain blocklist AND has zero biological/organism vocabulary is
        # unambiguous — pure politics/sociology/religion/humanities/tech. Only
        # for flagged records: an unflagged one has no off-domain evidence, so
        # missing vocabulary alone (e.g. a coral paper) isn't enough.
        if doc.get("flagged_stage1") and not _BIO_TERM_RE.search(text):
            is_relevant, reason = False, "no biological/organism terms found — auto-excluded without LLM call"
            counts["auto_excluded_no_bio_terms"] += 1
        else:
            async with sem:
                is_relevant, reason = await _classify_domain_relevance(title, abstract, model=model)
            if reason == DOMAIN_GATE_FAILED_REASON:
                # Leave unreviewed so the next run retries it.
                counts["error"] += 1
                return
        counts["relevant" if is_relevant else "excluded"] += 1

        if not dry_run:
            await db.abstracts.update_many(
                {"doc_id": doc["doc_id"]},
                {"$set": {
                    "is_relevant": is_relevant,
                    "exclusion_reason": None if is_relevant else reason,
                    "review_reason": reason,
                    "review_version": DOMAIN_GATE_VERSION,
                    "reviewed_at": datetime.now(timezone.utc),
                }},
            )

    async for batch in _stage2_batches(db, scope, batch_size, limit):
        await asyncio.gather(*[_review(d) for d in batch])
        done += len(batch)
        elapsed = time.time() - start
        logger.info(
            "  Stage 2: %d reviewed (%.2f/s) — relevant=%d excluded=%d "
            "(%d auto, no-LLM) errors=%d",
            done, done / max(elapsed, 0.001), counts["relevant"], counts["excluded"],
            counts["auto_excluded_no_bio_terms"], counts["error"],
        )

    logger.info(
        "Stage 2 done: relevant=%d excluded=%d (%d auto-excluded without an LLM call) "
        "errors=%d (left unreviewed) in %.0fs",
        counts["relevant"], counts["excluded"], counts["auto_excluded_no_bio_terms"],
        counts["error"], time.time() - start,
    )


# ---------------------------------------------------------------------------
# Propagate — apply Mongo verdicts to the canonical stores.
# ---------------------------------------------------------------------------

# Edge collections that can make a document reachable from the graph or the
# chat tools (taxon scope, topic/author browsing, citation graph). ``sf_support``
# and ``knowledge_graph`` can also hang off facts.
_DOC_EDGE_COLLECTIONS = ["knowledge_graph", "citations", "authored", "has_topic"]
_FACT_EDGE_COLLECTIONS = ["sf_support", "knowledge_graph"]


async def _load_verdicts(db) -> Tuple[Dict[str, str], List[str], int]:
    """Collapse per-copy verdicts to one per doc_id.

    Returns (excluded doc_id → reason, vetted-relevant doc_ids, conflicts).
    Only current-version "relevant" verdicts count as vetted. A doc_id with
    copies judged both ways is kept — the same fail-open asymmetry the
    classifier uses.
    """
    excluded: Dict[str, str] = {}
    any_relevant: set = set()
    vetted: set = set()
    async for d in db.abstracts.find(
        {"is_relevant": {"$in": [True, False]}},
        {"doc_id": 1, "is_relevant": 1, "exclusion_reason": 1, "review_version": 1, "_id": 0},
        batch_size=20000,
    ):
        k = d.get("doc_id")
        if not k:
            continue
        if d["is_relevant"]:
            any_relevant.add(k)
            if d.get("review_version") == DOMAIN_GATE_VERSION:
                vetted.add(k)
        else:
            excluded.setdefault(k, d.get("exclusion_reason") or "off-topic per domain gate")
    conflicts = [k for k in excluded if k in any_relevant]
    for k in conflicts:
        del excluded[k]
    return excluded, sorted(vetted), len(conflicts)


def _purge_batch(a, chroma, keys: List[str], reasons: Dict[str, str], dry_run: bool) -> Dict[str, int]:
    """Exclude one batch of documents and delete everything derived from them.

    ``chroma=None`` leaves the vectors alone — for when another process holds
    the embedded store open. The caller must then delete them by
    ``document_id`` afterwards; the chunk keys are gone with the Arango chunks.
    """
    doc_ids = [f"documents/{k}" for k in keys]
    q = a.aql
    n: Dict[str, int] = {}

    n["documents"] = q(
        "RETURN LENGTH(FOR k IN @ks FILTER DOCUMENT('documents', k) != null RETURN 1)",
        {"ks": keys})[0]
    fact_ids = q("FOR f IN facts FILTER f.document_id IN @ks RETURN f._id", {"ks": keys})
    chunk_keys = q("FOR c IN chunks FILTER c.document_id IN @ks RETURN c._key", {"ks": keys})
    embedded = q(
        "FOR k IN @ks LET d = DOCUMENT('documents', k) "
        "FILTER d.embedding_status == 'embedded' RETURN k", {"ks": keys})
    n["facts"] = len(fact_ids)
    n["chunks"] = len(chunk_keys)
    n["embedded_docs"] = len(embedded)

    for col in _DOC_EDGE_COLLECTIONS:
        n[f"edges:{col}"] = q(
            f"RETURN LENGTH(FOR e IN {col} FILTER e._from IN @ids OR e._to IN @ids RETURN 1)",
            {"ids": doc_ids})[0]
    for col in _FACT_EDGE_COLLECTIONS:
        n[f"edges:{col}(facts)"] = q(
            f"RETURN LENGTH(FOR e IN {col} FILTER e._from IN @ids OR e._to IN @ids RETURN 1)",
            {"ids": fact_ids})[0] if fact_ids else 0

    if dry_run:
        return n

    # Vectors first: if a later step fails, a re-run still finds the Arango
    # chunks and retries — the reverse order could orphan vectors.
    if chroma is not None:
        for i in range(0, len(chunk_keys), 5000):
            chroma.collection.delete(ids=chunk_keys[i:i + 5000])
        if embedded:
            # Catch-all for vectors whose Arango chunk record never got written.
            chroma.collection.delete(where={"document_id": {"$in": embedded}})

    for col in _FACT_EDGE_COLLECTIONS:
        if fact_ids:
            q(f"FOR e IN {col} FILTER e._from IN @ids OR e._to IN @ids REMOVE e IN {col}",
              {"ids": fact_ids})
    for col in _DOC_EDGE_COLLECTIONS:
        q(f"FOR e IN {col} FILTER e._from IN @ids OR e._to IN @ids REMOVE e IN {col}",
          {"ids": doc_ids})
    q("FOR e IN chunk_belongs_to FILTER e._to IN @ids REMOVE e IN chunk_belongs_to",
      {"ids": doc_ids})
    q("FOR c IN chunks FILTER c.document_id IN @ks REMOVE c IN chunks", {"ks": keys})
    q("FOR f IN facts FILTER f.document_id IN @ks REMOVE f IN facts", {"ks": keys})
    q(
        "FOR k IN @ks LET d = DOCUMENT('documents', k) FILTER d != null "
        "UPDATE d WITH {processing_status: 'excluded', is_relevant: false, "
        "exclusion_reason: @reasons[k], "
        "embedding_status: d.embedding_status == null ? null : 'excluded', "
        "num_facts: 0, num_chunks: 0, updated_at: @t} IN documents",
        {"ks": keys, "reasons": {k: reasons[k] for k in keys},
         "t": datetime.now(timezone.utc).isoformat()},
    )
    return n


async def run_propagate(db, batch_size: int, limit: int, dry_run: bool) -> None:
    excluded, relevant, conflicts = await _load_verdicts(db)
    logger.info(
        "Propagate: %d doc_ids judged off-domain, %d relevant, %d conflicting "
        "(kept) — dry_run=%s", len(excluded), len(relevant), conflicts, dry_run,
    )
    a = _arango()
    chroma = None
    if not dry_run:
        from advandeb_kb.services.chromadb_service import ChromaDBService

        chroma = ChromaDBService()
        logger.info("ChromaDB vectors before: %d", chroma.count())

    # Mark confirmed-relevant docs so the extraction and embedding jobs can
    # tell vetted abstracts from never-reviewed ones.
    if limit:
        relevant = relevant[:limit]
    if not dry_run:
        for i in range(0, len(relevant), batch_size):
            a.aql(
                "FOR k IN @ks LET d = DOCUMENT('documents', k) "
                "FILTER d != null AND d.is_relevant != true "
                "UPDATE d WITH {is_relevant: true} IN documents",
                {"ks": relevant[i:i + batch_size]})
        logger.info("Marked %d relevant documents", len(relevant))

    keys = sorted(excluded)
    if limit:
        keys = keys[:limit]
    totals: Dict[str, int] = {}
    start = time.time()
    for i in range(0, len(keys), batch_size):
        n = _purge_batch(a, chroma, keys[i:i + batch_size], excluded, dry_run)
        for k, v in n.items():
            totals[k] = totals.get(k, 0) + v
        done = min(i + batch_size, len(keys))
        if (i // batch_size) % 20 == 0 or done == len(keys):
            logger.info("  Propagate: %d/%d — %s (%.0fs)", done, len(keys), totals, time.time() - start)

    verb = "would remove" if dry_run else "removed"
    logger.info("Propagate done: %s for %d off-domain documents — %s",
                verb, totals.get("documents", 0), totals)
    if chroma is not None:
        logger.info("ChromaDB vectors after: %d", chroma.count())


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
    parser.add_argument("--propagate", action="store_true",
                        help="Apply verdicts to ArangoDB + ChromaDB (exclude docs, delete derived data)")
    parser.add_argument("--report", action="store_true", help="Print current tag counts")
    parser.add_argument(
        "--scope", choices=["flagged", "facts", "in-kb"], default="flagged",
        help="Stage 2 candidates: stage-1 shortlist (default); unreviewed abstracts "
             "that produced facts; or that produced facts or were embedded",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max docs to process (0 = all)")
    parser.add_argument("--batch-size", type=int, default=5000,
                        help="Stage 1 cursor batch size (stage 2 uses --review-batch)")
    parser.add_argument("--review-batch", type=int, default=500,
                        help="Stage 2 docs per batch / propagate docs per batch")
    parser.add_argument("--concurrency", type=int, default=4, help="Stage 2 parallel Ollama calls")
    parser.add_argument("--dry-run", action="store_true",
                        help="Stage 2: classify but don't write; propagate: count only")
    parser.add_argument(
        "--model", default=None,
        help="Ollama model for stage 2 (default: settings.OLLAMA_MODEL). "
             "This is a simple binary judgment — a small/fast model (e.g. gemma2:2b) "
             "is recommended for a corpus this large.",
    )
    parser.add_argument("--mongodb-url", default="mongodb://localhost:27017")
    args = parser.parse_args()

    if not (args.stage1 or args.stage2 or args.propagate or args.report):
        parser.error("Specify one of --stage1, --stage2, --propagate, --report")

    client = AsyncIOMotorClient(args.mongodb_url)
    db = client[DB_NAME]

    async def _main():
        if args.stage1:
            await run_stage1(db, args.batch_size, args.limit)
        if args.stage2:
            await run_stage2(db, args.scope, args.concurrency, args.review_batch,
                             args.limit, args.dry_run, args.model)
        if args.propagate:
            await run_propagate(db, args.review_batch, args.limit, args.dry_run)
        if args.report:
            await run_report(db)

    asyncio.run(_main())
    client.close()


if __name__ == "__main__":
    main()
