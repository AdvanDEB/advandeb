"""
Import the OpenAlex *reproduction* abstract corpus into the ArangoDB KB store
(``advandeb_kb``) as ``documents`` tagged ``general_domain="reproduction"``.

This feeds the new "reproduction" knowledge graph. Documents are imported with
``processing_status="pending"`` so that ``run_reproduction_pipeline.py`` can later
pick them up and run LLM fact-extraction + stylized-fact matching.

IMPORTANT — this writes to **ArangoDB**, not MongoDB. (The older
``import_openalex_abstracts.py`` targets MongoDB, which is now only used for
ingestion-workflow state; KB knowledge data lives in ArangoDB.)

Deduplication: the source ``abstracts.jsonl`` contains ~4.6M rows but only
~1.18M unique works (the same paper is returned by many overlapping search
queries). We dedupe to one node per paper by using the OpenAlex id as the
ArangoDB ``_key`` and importing with ``on_duplicate="ignore"`` — so re-runs and
duplicates never clobber a document the pipeline has already processed.

Connection config comes from ``advandeb_kb.config.settings`` (env-driven). The
caller MUST export the Arango credentials first, e.g.:

    cd /home/adeb/dev/advandeb
    set -a && . app/backend/.env && set +a

Usage:
    # Dry-run — parse + show samples, no DB connection, no writes:
    conda run -n advandeb python knowledge-builder/scripts/import_reproduction_abstracts.py \\
        --mode abstracts --dry-run --limit 5

    # Full import (run in the background — takes a while on 7.7GB):
    nohup conda run -n advandeb python knowledge-builder/scripts/import_reproduction_abstracts.py \\
        > /tmp/repro_import.log 2>&1 &

    # Optional 2nd pass: build citation edges among imported docs (works mode):
    conda run -n advandeb python knowledge-builder/scripts/import_reproduction_abstracts.py \\
        --mode works --build-citations
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.config.settings import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("import_reproduction")

GENERAL_DOMAIN = "reproduction"
DEFAULT_SOURCE = os.path.expanduser(
    "~/dev/advandeb_auxiliary/abstracts_reproduction/data_full_reproduction"
)
BULK_SIZE = 2_000


# ---------------------------------------------------------------------------
# Text / field helpers (mapping mirrors import_openalex_abstracts.py)
# ---------------------------------------------------------------------------

def _sanitize(text: Optional[str]) -> str:
    """Drop unpaired surrogates that crash downstream encoders."""
    if not text:
        return ""
    return text.encode("utf-8", errors="ignore").decode("utf-8")


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """Reconstruct abstract text from an OpenAlex abstract_inverted_index."""
    if not inverted_index:
        return ""
    word_pos: List[tuple] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_pos.append((pos, word))
    word_pos.sort(key=lambda x: x[0])
    return " ".join(w for _, w in word_pos)


def _clean_doi(doi_raw: Optional[str]) -> Optional[str]:
    if not doi_raw:
        return None
    doi = doi_raw.strip()
    for prefix in ("https://doi.org/", "http://doi.org/"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.lower() or None


def _extract_authors(authorships: Optional[List[Dict]]) -> List[str]:
    if not authorships:
        return []
    return [
        a["author"]["display_name"]
        for a in authorships
        if a.get("author", {}).get("display_name")
    ][:20]


def _extract_journal(primary_location: Optional[Dict]) -> Optional[str]:
    if not primary_location:
        return None
    source = primary_location.get("source") or {}
    return source.get("display_name") or None


def _extract_tags(concepts: Optional[List], keywords: Optional[List]) -> List[str]:
    tags = set()
    for c in (concepts or []):
        name = c.get("display_name")
        if name and c.get("score", 0) >= 0.4:
            tags.add(name)
    for k in (keywords or []):
        name = k.get("display_name")
        if name:
            tags.add(name)
    return sorted(tags)[:30]


def _strip_openalex_id(openalex_url: Optional[str]) -> str:
    """'https://openalex.org/W123' -> 'W123' (a valid ArangoDB _key)."""
    if not openalex_url:
        return ""
    return openalex_url.rsplit("/", 1)[-1].strip()


def document_key(openalex_id: str, doi: Optional[str], title: str, year: Any) -> str:
    """Deterministic, valid ArangoDB _key. Prefer OpenAlex id; fall back to DOI/title hash."""
    oa = _strip_openalex_id(openalex_id)
    if oa:
        return oa
    if doi:
        return "doi_" + hashlib.sha1(doi.encode("utf-8")).hexdigest()[:20]
    return "rec_" + hashlib.sha1(f"{title}|{year}".encode("utf-8")).hexdigest()[:20]


def record_to_document(record: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """Map an OpenAlex work/abstract record to an ArangoDB documents entry."""
    openalex_id = record.get("id", "") or ""
    doi = _clean_doi(record.get("doi"))
    title = _sanitize(record.get("display_name") or record.get("title") or "")
    year = record.get("publication_year") or record.get("year")
    abstract = _sanitize(
        record.get("abstract")
        or reconstruct_abstract(record.get("abstract_inverted_index"))
    )

    doc: Dict[str, Any] = {
        "_key": document_key(openalex_id, doi, title, year),
        "title": title,
        "doi": doi,
        "authors": _extract_authors(record.get("authorships")),
        "year": int(year) if isinstance(year, (int, str)) and str(year).isdigit() else None,
        "journal": _extract_journal(record.get("primary_location")),
        "abstract": abstract,
        "content": abstract,  # abstract is the searchable content for these docs
        "source_type": "web",
        "source_path": openalex_id,
        "general_domain": GENERAL_DOMAIN,
        "processing_status": "pending",  # contract: pipeline runner picks these up
        "openalex_id": openalex_id,
        "tags": _extract_tags(record.get("concepts"), record.get("keywords")),
        "cited_by_count": record.get("cited_by_count"),
        "language": record.get("language"),
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    return doc


# ---------------------------------------------------------------------------
# Streaming reader
# ---------------------------------------------------------------------------

def iter_records(source_dir: str, mode: str, limit: Optional[int]) -> Iterator[Dict]:
    filename = "works.jsonl" if mode == "works" else "abstracts.jsonl"
    path = Path(os.path.expanduser(source_dir)) / filename
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    logger.info("Streaming %s …", path)
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("JSON parse error near line %d: %s", count + 1, e)
                continue
            count += 1
            if limit and count >= limit:
                break


# ---------------------------------------------------------------------------
# Arango helpers
# ---------------------------------------------------------------------------

def ensure_indexes(a) -> None:
    """Ensure collections exist and the indexes the pipeline runner relies on."""
    a.setup_schema()  # idempotent: creates documents collection + base indexes
    col = a.db.collection("documents")
    existing = [idx["fields"] for idx in col.indexes()]
    for fields, sparse in [(["general_domain"], False),
                           (["processing_status"], False),
                           (["openalex_id"], True)]:
        if fields not in existing:
            try:
                col.add_persistent_index(fields=fields, sparse=sparse)
                logger.info("Created index on documents%s", fields)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Index %s skipped: %s", fields, exc)


def flush_batch(a, batch: List[Dict], on_duplicate: str) -> Dict[str, int]:
    """Bulk import a batch into documents. on_duplicate='ignore' preserves existing docs."""
    if not batch:
        return {"created": 0, "errors": 0}
    res = a.db.collection("documents").import_bulk(
        batch, on_duplicate=on_duplicate, halt_on_error=False
    )
    return {"created": res.get("created", 0), "errors": res.get("errors", 0)}


# ---------------------------------------------------------------------------
# Import passes
# ---------------------------------------------------------------------------

def run_import(source_dir: str, mode: str, limit: Optional[int], dry_run: bool,
               batch_size: int, on_duplicate: str) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    processed = created = errors = mapped_errors = 0

    if dry_run:
        logger.info("DRY-RUN — no DB connection, no writes")
        for i, record in enumerate(iter_records(source_dir, mode, limit or 5), 1):
            doc = record_to_document(record, now_iso)
            logger.info(
                "  sample %d: _key=%s doi=%r year=%s authors=%d abstract=%d chars title=%r",
                i, doc["_key"], doc["doi"], doc["year"], len(doc["authors"]),
                len(doc["content"]), doc["title"][:70],
            )
            processed += 1
        logger.info("DRY-RUN complete — %d records parsed", processed)
        return {"processed": processed, "created": 0, "dry_run": True}

    from advandeb_kb.database.arango_client import ArangoDatabase
    a = ArangoDatabase()
    a.connect()
    ensure_indexes(a)

    batch: List[Dict] = []
    seen_in_batch: set = set()
    for record in iter_records(source_dir, mode, limit):
        try:
            doc = record_to_document(record, now_iso)
        except Exception as exc:  # noqa: BLE001
            mapped_errors += 1
            continue
        processed += 1
        # de-dupe within the in-flight batch (import_bulk also ignores cross-run dupes)
        if doc["_key"] in seen_in_batch:
            continue
        seen_in_batch.add(doc["_key"])
        batch.append(doc)

        if len(batch) >= batch_size:
            r = flush_batch(a, batch, on_duplicate)
            created += r["created"]
            errors += r["errors"]
            batch.clear()
            seen_in_batch.clear()
            if processed % 50_000 == 0:
                logger.info("  %d rows read, %d new docs created, %d errors …",
                            processed, created, errors)

    r = flush_batch(a, batch, on_duplicate)
    created += r["created"]
    errors += r["errors"]

    total_repro = a.aql(
        "RETURN LENGTH(FOR d IN documents FILTER d.general_domain==@g RETURN 1)",
        {"g": GENERAL_DOMAIN},
    )[0]
    logger.info(
        "IMPORT complete — rows=%d, new=%d, bulk_errors=%d, map_errors=%d | "
        "documents tagged '%s' now: %d",
        processed, created, errors, mapped_errors, GENERAL_DOMAIN, total_repro,
    )
    return {"processed": processed, "created": created, "errors": errors,
            "total_reproduction": total_repro}


def run_build_citations(source_dir: str, limit: Optional[int], batch_size: int) -> Dict[str, Any]:
    """2nd pass (works mode): citation edges among imported reproduction docs."""
    from advandeb_kb.database.arango_client import ArangoDatabase
    a = ArangoDatabase()
    a.connect()

    logger.info("Loading existing reproduction document keys into memory …")
    keys = set(a.aql(
        "FOR d IN documents FILTER d.general_domain==@g RETURN d._key", {"g": GENERAL_DOMAIN}
    ))
    logger.info("  %d reproduction docs available as citation targets", len(keys))

    edge_batch: List[Dict] = []
    made = errors = 0
    for record in iter_records(source_dir, "works", limit):
        citing = document_key(record.get("id", ""), _clean_doi(record.get("doi")),
                              record.get("display_name") or "", record.get("publication_year"))
        if citing not in keys:
            continue
        for ref in record.get("referenced_works") or []:
            cited = _strip_openalex_id(ref)
            if cited and cited in keys and cited != citing:
                edge_batch.append({
                    "_key": f"{citing}__{cited}",
                    "_from": f"documents/{citing}",
                    "_to": f"documents/{cited}",
                })
        if len(edge_batch) >= batch_size:
            res = a.db.collection("citations").import_bulk(
                edge_batch, on_duplicate="ignore", halt_on_error=False)
            made += res.get("created", 0)
            errors += res.get("errors", 0)
            edge_batch.clear()
    if edge_batch:
        res = a.db.collection("citations").import_bulk(
            edge_batch, on_duplicate="ignore", halt_on_error=False)
        made += res.get("created", 0)
        errors += res.get("errors", 0)
    logger.info("CITATIONS pass complete — edges created=%d, errors=%d", made, errors)
    return {"edges_created": made, "errors": errors}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default=DEFAULT_SOURCE,
                   help=f"Dir with works.jsonl / abstracts.jsonl (default: {DEFAULT_SOURCE})")
    p.add_argument("--mode", choices=["abstracts", "works"], default="abstracts",
                   help="abstracts.jsonl (light, pre-built text) or works.jsonl (full metadata). "
                        "Default: abstracts")
    p.add_argument("--limit", type=int, default=None, help="Max rows to read (default: all)")
    p.add_argument("--batch-size", type=int, default=BULK_SIZE)
    p.add_argument("--on-duplicate", choices=["ignore", "replace"], default="ignore",
                   help="'ignore' preserves docs the pipeline already processed (default)")
    p.add_argument("--dry-run", action="store_true", help="Parse + show samples, no writes")
    p.add_argument("--build-citations", action="store_true",
                   help="2nd pass: build citation edges (requires --mode works; run AFTER import)")
    args = p.parse_args()

    if args.build_citations:
        run_build_citations(args.source, args.limit, args.batch_size)
        return
    run_import(args.source, args.mode, args.limit, args.dry_run,
               args.batch_size, args.on_duplicate)


if __name__ == "__main__":
    main()
