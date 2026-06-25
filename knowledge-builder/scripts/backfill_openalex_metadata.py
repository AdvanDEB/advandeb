"""
Backfill OpenAlex citation/retraction metadata onto the ArangoDB ``documents``
collection, and (optionally) materialize intra-corpus ``citations`` edges.

WHY: ``documents`` has ``openalex_id`` (and the ``_key`` *is* the OpenAlex short
ID, e.g. ``W100004512``) but ``cited_by_count`` / ``is_retracted`` /
``referenced_works`` were never populated — so the chat cannot answer
citation-impact / retraction ("zombie theory") questions. This job fetches those
fields from the OpenAlex API in batches and writes them back.

The data exists upstream — verified e.g. W100004512 → cited_by_count=186, 70 refs.

IDEMPOTENT + RESUMABLE: each processed doc is flagged ``openalex_enriched=true``;
re-running only touches the remainder. Safe to Ctrl-C and restart.

Phase 1 (default): enrich documents with cited_by_count / is_retracted /
                   referenced_works (stored as short W-ids).
Phase 2 (--build-edges): create ``citations`` edges (src -> ref) for references
                   whose target document exists in the corpus.

Connection + polite-pool email come from advandeb_kb.config.settings (env-driven).

Usage:
    # Dry-run a small slice (no writes):
    conda run -n advandeb python knowledge-builder/scripts/backfill_openalex_metadata.py \
        --limit 200 --dry-run

    # Full backfill (long — ~3.9M docs / 50 per request; run in background):
    nohup conda run -n advandeb python knowledge-builder/scripts/backfill_openalex_metadata.py \
        > /tmp/oa_backfill.log 2>&1 &

    # 2nd pass: build citation edges among enriched docs:
    conda run -n advandeb python knowledge-builder/scripts/backfill_openalex_metadata.py \
        --build-edges > /tmp/oa_edges.log 2>&1 &
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

# Load app/backend/.env so Arango credentials are present when run standalone.
try:
    from pathlib import Path as _Path

    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(_Path(__file__).resolve().parents[2] / "app" / "backend" / ".env")
except Exception:
    pass

from advandeb_kb.config.settings import settings
from advandeb_kb.database.arango_client import ArangoDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("oa_backfill")

OPENALEX_URL = "https://api.openalex.org/works"
# OpenAlex OR-filter caps multi-value filters at 50 values per request.
MAX_BATCH = 50
SELECT = "id,cited_by_count,is_retracted,referenced_works"


def _connect() -> ArangoDatabase:
    db = ArangoDatabase(
        url=settings.ARANGO_URL,
        db_name=settings.ARANGO_DB_NAME,
        username=settings.ARANGO_USERNAME,
        password=settings.ARANGO_PASSWORD,
    )
    db.connect()
    return db


def _short_id(oa: Optional[str]) -> Optional[str]:
    """'https://openalex.org/W123' -> 'W123' (also passes through bare 'W123')."""
    if not oa:
        return None
    return oa.rstrip("/").rsplit("/", 1)[-1]


def _fetch_batch(
    client: httpx.Client, ids: List[str], retries: int = 5
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Fetch a batch of works by short id; return {short_id: {cbc, retr, refs}}.

    Returns None on permanent failure (e.g. exhausted 429 retries) so the caller
    can leave those ids for a later run instead of flagging them done with no data.
    """
    params = {
        "filter": "openalex_id:" + "|".join(ids),
        "select": SELECT,
        "per-page": MAX_BATCH,
        "mailto": settings.OPENALEX_EMAIL,
    }
    delay = 1.0
    for attempt in range(retries):
        try:
            resp = client.get(OPENALEX_URL, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("429 rate-limited; backing off %.1fs", delay)
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            resp.raise_for_status()
            out: Dict[str, Dict[str, Any]] = {}
            for w in resp.json().get("results", []):
                sid = _short_id(w.get("id"))
                if not sid:
                    continue
                out[sid] = {
                    "cited_by_count": w.get("cited_by_count"),
                    "is_retracted": bool(w.get("is_retracted")),
                    "referenced_works": [
                        _short_id(r) for r in (w.get("referenced_works") or []) if r
                    ],
                }
            return out
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("batch fetch failed (attempt %d): %s", attempt + 1, exc)
            time.sleep(delay)
            delay = min(delay * 2, 60)
    logger.error("batch permanently failed for %d ids — marking enriched with no data", len(ids))
    return {}


def _chunks(seq: List[str], n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def enrich(db: ArangoDatabase, batch_size: int, limit: int, sleep: float, dry_run: bool) -> None:
    batch_size = min(batch_size, MAX_BATCH)
    client = httpx.Client(headers={"User-Agent": f"advandeb/1.0 ({settings.OPENALEX_EMAIL})"})
    processed = updated = retracted = 0
    page = 2000  # docs pulled from Arango per outer iteration
    try:
        while True:
            keys = db.aql(
                "FOR d IN documents "
                "FILTER d.openalex_enriched != true AND d._key LIKE 'W%' "
                "LIMIT @n RETURN d._key",
                bind_vars={"n": page if limit == 0 else min(page, limit - processed)},
            )
            if not keys:
                break
            for chunk in _chunks(keys, batch_size):
                data = _fetch_batch(client, chunk)
                if data is None:
                    logger.warning("batch failed — leaving %d ids for a later run", len(chunk))
                    if sleep:
                        time.sleep(sleep)
                    continue
                updates = []
                for k in chunk:
                    rec = data.get(k)
                    if rec is None:
                        # Not returned by OpenAlex (merged/deleted) — flag so we
                        # don't keep re-fetching it forever.
                        updates.append({"_key": k, "cited_by_count": None,
                                        "is_retracted": None, "referenced_works": None})
                        continue
                    updates.append({"_key": k, **rec})
                    if rec.get("is_retracted"):
                        retracted += 1
                processed += len(chunk)
                if dry_run:
                    sample = next((u for u in updates if u.get("cited_by_count")), updates[0])
                    logger.info("[dry-run] would update %d docs (e.g. %s cbc=%s refs=%s)",
                                len(updates), sample["_key"], sample.get("cited_by_count"),
                                len(sample.get("referenced_works") or []) if sample.get("referenced_works") else 0)
                else:
                    db.aql(
                        "FOR u IN @ups UPDATE u._key WITH {"
                        " cited_by_count: u.cited_by_count,"
                        " is_retracted: u.is_retracted,"
                        " referenced_works: u.referenced_works,"
                        " openalex_enriched: true,"
                        " openalex_enriched_at: DATE_ISO8601(DATE_NOW())"
                        "} IN documents OPTIONS { ignoreErrors: true }",
                        bind_vars={"ups": updates},
                    )
                    updated += len(updates)
                if processed % 1000 == 0:
                    logger.info("progress: processed=%d updated=%d retracted_found=%d",
                                processed, updated, retracted)
                if sleep:
                    time.sleep(sleep)
                if limit and processed >= limit:
                    break
            if dry_run or (limit and processed >= limit):
                break
    finally:
        client.close()
    logger.info("DONE enrich: processed=%d updated=%d retracted_found=%d", processed, updated, retracted)


def enrich_fact_sources(db: ArangoDatabase, batch_size: int, sleep: float, dry_run: bool) -> None:
    """Enrich ONLY the documents that source extracted facts (the ~12k docs that
    actually appear in claim_consensus / fact-based answers).

    These are hex-keyed (not W-keyed) but carry an ``openalex_id``; we fetch by
    that id and write back to the hex ``_key``. This is the set the citation tool
    needs — small and fast, unlike the full 3.9M W-doc corpus.
    """
    batch_size = min(batch_size, MAX_BATCH)
    targets = db.aql(
        "LET fsrc = (FOR f IN facts FILTER f.document_id != null RETURN DISTINCT f.document_id) "
        "FOR did IN fsrc "
        "  LET d = DOCUMENT('documents', did) "
        "  FILTER d != null AND d.openalex_id != null "
        "  FILTER d.cited_by_count == null "  # skip ones already enriched with data
        "  RETURN { key: d._key, oa: d.openalex_id }"
    )
    logger.info("fact-source docs needing enrichment: %d", len(targets))
    # Map OpenAlex short id -> our (hex) document key(s).
    wid_to_keys: Dict[str, List[str]] = {}
    for t in targets:
        sid = _short_id(t["oa"])
        if sid:
            wid_to_keys.setdefault(sid, []).append(t["key"])
    wids = list(wid_to_keys)
    client = httpx.Client(headers={"User-Agent": f"advandeb/1.0 ({settings.OPENALEX_EMAIL})"})
    done = updated = retracted = 0
    try:
        for chunk in _chunks(wids, batch_size):
            data = _fetch_batch(client, chunk)
            if data is None:
                logger.warning("batch failed — leaving %d ids for a later run", len(chunk))
                if sleep:
                    time.sleep(sleep)
                continue
            updates = []
            for wid in chunk:
                rec = data.get(wid)
                if rec is None:
                    continue  # OpenAlex didn't return it; leave for retry
                if rec.get("is_retracted"):
                    retracted += 1
                for key in wid_to_keys[wid]:
                    updates.append({"_key": key, **rec})
            done += len(chunk)
            if dry_run:
                ex = next((u for u in updates if u.get("cited_by_count")), updates[0] if updates else None)
                logger.info("[dry-run] would update %d docs%s", len(updates),
                            f" (e.g. {ex['_key']} cbc={ex.get('cited_by_count')})" if ex else "")
            elif updates:
                db.aql(
                    "FOR u IN @ups UPDATE u._key WITH {"
                    " cited_by_count: u.cited_by_count, is_retracted: u.is_retracted,"
                    " referenced_works: u.referenced_works, openalex_enriched: true,"
                    " openalex_enriched_at: DATE_ISO8601(DATE_NOW())"
                    "} IN documents OPTIONS { ignoreErrors: true }",
                    bind_vars={"ups": updates},
                )
                updated += len(updates)
            if sleep:
                time.sleep(sleep)
    finally:
        client.close()
    logger.info("DONE fact-source enrich: wids=%d updated=%d retracted_found=%d", done, updated, retracted)


def _norm_doi(doi: Optional[str]) -> Optional[str]:
    """Normalize to bare lowercase DOI ('10.x/...'), stripping any URL prefix."""
    if not doi:
        return None
    d = doi.strip().lower()
    for pre in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(pre):
            d = d[len(pre):]
    return d or None


def _fetch_batch_by_doi(
    client: httpx.Client, dois: List[str], retries: int = 5
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Fetch works by DOI; return {normalized_doi: {cbc, retr, refs}} or None."""
    params = {
        "filter": "doi:" + "|".join(dois),
        "select": "doi,cited_by_count,is_retracted,referenced_works",
        "per-page": MAX_BATCH,
        "mailto": settings.OPENALEX_EMAIL,
    }
    delay = 1.0
    for attempt in range(retries):
        try:
            resp = client.get(OPENALEX_URL, params=params, timeout=60)
            if resp.status_code == 429:
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            resp.raise_for_status()
            out: Dict[str, Dict[str, Any]] = {}
            for w in resp.json().get("results", []):
                nd = _norm_doi(w.get("doi"))
                if not nd:
                    continue
                out[nd] = {
                    "cited_by_count": w.get("cited_by_count"),
                    "is_retracted": bool(w.get("is_retracted")),
                    "referenced_works": [
                        _short_id(r) for r in (w.get("referenced_works") or []) if r
                    ],
                }
            return out
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("doi batch fetch failed (attempt %d): %s", attempt + 1, exc)
            time.sleep(delay)
            delay = min(delay * 2, 60)
    return None


def enrich_consensus_docs(db: ArangoDatabase, batch_size: int, sleep: float, dry_run: bool) -> None:
    """Enrich the documents linked to stylized facts via ``sf_support`` — the
    exact references that appear in ``claim_consensus`` answers.

    These docs have DOIs but no ``openalex_id``, so we fetch by DOI. This is the
    population the citation/retraction signals need (~1.2k docs).
    """
    batch_size = min(batch_size, MAX_BATCH)
    rows = db.aql(
        "LET sf_docs = (FOR e IN sf_support LET f = DOCUMENT(e._from) "
        "  FILTER f != null AND f.document_id != null RETURN DISTINCT f.document_id) "
        "FOR did IN sf_docs "
        "  LET d = DOCUMENT(CONCAT('documents/', did)) "
        "  FILTER d != null AND d.doi != null AND d.doi != '' AND d.cited_by_count == null "
        "  RETURN { key: d._key, doi: d.doi }"
    )
    logger.info("consensus (sf_support-linked) docs needing enrichment: %d", len(rows))
    # normalized DOI -> [doc keys]
    doi_to_keys: Dict[str, List[str]] = {}
    for r in rows:
        nd = _norm_doi(r["doi"])
        if nd:
            doi_to_keys.setdefault(nd, []).append(r["key"])
    dois = list(doi_to_keys)
    client = httpx.Client(headers={"User-Agent": f"advandeb/1.0 ({settings.OPENALEX_EMAIL})"})
    done = updated = retracted = 0
    try:
        for chunk in _chunks(dois, batch_size):
            data = _fetch_batch_by_doi(client, chunk)
            if data is None:
                logger.warning("doi batch failed — leaving %d for a later run", len(chunk))
                if sleep:
                    time.sleep(sleep)
                continue
            updates = []
            for nd in chunk:
                rec = data.get(nd)
                if rec is None:
                    continue
                if rec.get("is_retracted"):
                    retracted += 1
                for key in doi_to_keys[nd]:
                    updates.append({"_key": key, **rec})
            done += len(chunk)
            if dry_run:
                ex = next((u for u in updates if u.get("cited_by_count")), updates[0] if updates else None)
                logger.info("[dry-run] would update %d docs%s", len(updates),
                            f" (e.g. {ex['_key']} cbc={ex.get('cited_by_count')})" if ex else "")
            elif updates:
                db.aql(
                    "FOR u IN @ups UPDATE u._key WITH {"
                    " cited_by_count: u.cited_by_count, is_retracted: u.is_retracted,"
                    " referenced_works: u.referenced_works, openalex_enriched: true,"
                    " openalex_enriched_at: DATE_ISO8601(DATE_NOW())"
                    "} IN documents OPTIONS { ignoreErrors: true }",
                    bind_vars={"ups": updates},
                )
                updated += len(updates)
            if sleep:
                time.sleep(sleep)
    finally:
        client.close()
    logger.info("DONE consensus enrich: dois=%d updated=%d retracted_found=%d", done, updated, retracted)


def build_edges(db: ArangoDatabase, limit: int, dry_run: bool) -> None:
    """Materialize citations edges (src -> referenced doc) where target exists."""
    processed = edges = 0
    page = 1000
    while True:
        rows = db.aql(
            "FOR d IN documents "
            "FILTER d.referenced_works != null AND LENGTH(d.referenced_works) > 0 "
            "AND d.citations_built != true "
            "LIMIT @n RETURN {key: d._key, refs: d.referenced_works}",
            bind_vars={"n": page if limit == 0 else min(page, limit - processed)},
        )
        if not rows:
            break
        for r in rows:
            src, refs = r["key"], r["refs"]
            # Keep only refs that exist as documents in our corpus.
            present = db.aql(
                "FOR k IN @refs FILTER DOCUMENT('documents', k) != null RETURN k",
                bind_vars={"refs": refs},
            )
            if not dry_run:
                if present:
                    db.aql(
                        "FOR t IN @present INSERT {"
                        " _key: CONCAT(@src, '_', t),"
                        " _from: CONCAT('documents/', @src),"
                        " _to: CONCAT('documents/', t)"
                        "} INTO citations OPTIONS { ignoreErrors: true, overwriteMode: 'ignore' }",
                        bind_vars={"present": present, "src": src},
                    )
                db.aql("UPDATE @key WITH { citations_built: true } IN documents OPTIONS { ignoreErrors: true }",
                       bind_vars={"key": src})
            edges += len(present)
            processed += 1
        logger.info("edges progress: docs=%d edges=%d", processed, edges)
        if dry_run or (limit and processed >= limit):
            break
    logger.info("DONE build_edges: docs=%d edges=%d", processed, edges)


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill OpenAlex metadata onto documents.")
    ap.add_argument("--batch-size", type=int, default=MAX_BATCH, help="IDs per OpenAlex request (<=50)")
    ap.add_argument("--limit", type=int, default=0, help="Max docs to process this run (0 = all)")
    ap.add_argument("--sleep", type=float, default=0.15, help="Seconds between API requests (polite pool)")
    ap.add_argument("--dry-run", action="store_true", help="Fetch + show samples, no DB writes")
    ap.add_argument("--build-edges", action="store_true", help="Phase 2: build citations edges instead of enriching")
    ap.add_argument("--fact-sources-only", action="store_true",
                    help="Enrich the fact-source docs by OpenAlex id (W-keyed population)")
    ap.add_argument("--consensus-docs", action="store_true",
                    help="Enrich sf_support-linked docs by DOI (the citation tool's references) — fast")
    args = ap.parse_args()

    db = _connect()
    logger.info("connected to ArangoDB %s / %s", settings.ARANGO_URL, settings.ARANGO_DB_NAME)
    if args.build_edges:
        build_edges(db, args.limit, args.dry_run)
    elif args.consensus_docs:
        enrich_consensus_docs(db, args.batch_size, args.sleep, args.dry_run)
    elif args.fact_sources_only:
        enrich_fact_sources(db, args.batch_size, args.sleep, args.dry_run)
    else:
        enrich(db, args.batch_size, args.limit, args.sleep, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
