"""
Import OpenAlex works (JSONL) into the `documents` MongoDB collection.

Each JSONL line is an OpenAlex Work object.  The script maps fields to the
advandeb_kb Document model and bulk-upserts into MongoDB.

Supports two input modes:
  --mode works   : reads works.jsonl — rich metadata + abstract_inverted_index
  --mode abstracts: reads abstracts.jsonl — lighter records with pre-built abstract text

Usage:
    # Test with first 1000 records:
    python scripts/import_openalex_abstracts.py \\
        --source ~/dev/advandeb_auxiliary/abstracts_reproduction/data_full \\
        --limit 1000

    # Full import (~4.6 M, takes 30–60 min):
    python scripts/import_openalex_abstracts.py \\
        --source ~/dev/advandeb_auxiliary/abstracts_reproduction/data_full_reproduction

    # Dry-run (no DB writes):
    python scripts/import_openalex_abstracts.py \\
        --source ~/dev/advandeb_auxiliary/abstracts_reproduction/data_full \\
        --dry-run --limit 5

Indexes created on documents:
    doi (sparse unique), openalex_id (sparse), source_type, publication_year
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.config.settings import settings
from advandeb_kb.database.mongodb import mongodb

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BULK_SIZE = 1_000  # documents per bulk_write call


# ---------------------------------------------------------------------------
# Abstract reconstruction
# ---------------------------------------------------------------------------

def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """Reconstruct abstract text from OpenAlex abstract_inverted_index."""
    if not inverted_index:
        return ""
    word_pos: List[tuple] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_pos.append((pos, word))
    word_pos.sort(key=lambda x: x[0])
    return " ".join(w for _, w in word_pos)


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def _clean_doi(doi_raw: Optional[str]) -> Optional[str]:
    """Strip URL prefix from DOI string."""
    if not doi_raw:
        return None
    doi = doi_raw.strip()
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]
    elif doi.startswith("http://doi.org/"):
        doi = doi[len("http://doi.org/"):]
    return doi or None


def _extract_authors(authorships: Optional[List[Dict]]) -> List[str]:
    if not authorships:
        return []
    return [
        a["author"]["display_name"]
        for a in authorships
        if a.get("author", {}).get("display_name")
    ][:20]  # cap at 20 authors


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


def work_to_document(record: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Map an OpenAlex Work record to a documents collection document."""
    doi = _clean_doi(record.get("doi"))
    openalex_id = record.get("id", "")

    # Abstract: prefer pre-built field, fall back to inverted index reconstruction
    abstract = record.get("abstract") or reconstruct_abstract(
        record.get("abstract_inverted_index")
    )

    return {
        "title": record.get("display_name") or record.get("title") or "",
        "doi": doi,
        "authors": _extract_authors(record.get("authorships")),
        "year": record.get("publication_year"),
        "journal": _extract_journal(record.get("primary_location")),
        "abstract": abstract,
        "content": abstract,  # use abstract as searchable content
        "source_type": "web",
        "source_path": openalex_id,
        "general_domain": "reproduction",
        "processing_status": "completed",
        # Extra metadata not in the base model — stored for future use
        "openalex_id": openalex_id,
        "tags": _extract_tags(
            record.get("concepts"), record.get("keywords")
        ),
        "cited_by_count": record.get("cited_by_count"),
        "is_oa": record.get("is_oa"),
        "language": record.get("language"),
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# Streaming reader
# ---------------------------------------------------------------------------

def iter_records(source_dir: str, mode: str, limit: Optional[int]) -> Iterator[Dict]:
    filename = "works.jsonl" if mode == "works" else "abstracts.jsonl"
    path = Path(source_dir) / filename
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    logger.info("Reading %s …", path)
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("JSON parse error at line %d: %s", count + 1, e)
                continue
            count += 1
            if limit and count >= limit:
                break


# ---------------------------------------------------------------------------
# Database import
# ---------------------------------------------------------------------------

async def ensure_indexes(db) -> None:
    col = db.documents
    await col.create_index("doi", sparse=True)
    await col.create_index("openalex_id", sparse=True)
    await col.create_index("source_type")
    await col.create_index("year")
    await col.create_index("general_domain")
    logger.info("Indexes ensured on documents")


async def upsert_batch(db, batch: List[Dict]) -> int:
    from pymongo import UpdateOne
    ops = [
        UpdateOne(
            # Upsert key: prefer openalex_id, fall back to doi, then title
            {"openalex_id": doc["openalex_id"]} if doc.get("openalex_id")
            else ({"doi": doc["doi"]} if doc.get("doi")
                  else {"title": doc["title"], "year": doc.get("year")}),
            {"$setOnInsert": doc},
            upsert=True,
        )
        for doc in batch
    ]
    result = await db.documents.bulk_write(ops, ordered=False)
    return result.upserted_count


async def run_import(
    source_dir: str,
    mode: str,
    limit: Optional[int],
    dry_run: bool,
    batch_size: int,
) -> Dict[str, Any]:
    now = datetime.utcnow()
    total = 0
    inserted = 0
    errors = 0

    records_iter = iter_records(source_dir, mode, limit)

    if dry_run:
        logger.info("Dry-run mode — no database writes")
        for i, record in enumerate(records_iter, 1):
            doc = work_to_document(record, now)
            if i <= 3:
                logger.info(
                    "  Sample %d: doi=%r title=%r year=%s authors=%d abstract=%d chars",
                    i, doc["doi"], doc["title"][:60],
                    doc["year"], len(doc["authors"]), len(doc["abstract"] or ""),
                )
            total += 1
        logger.info("Dry-run complete — %d records parsed", total)
        return {"total": total, "inserted": 0, "dry_run": True}

    await mongodb.connect()
    db = mongodb.database
    await ensure_indexes(db)

    batch: List[Dict] = []
    for record in records_iter:
        try:
            doc = work_to_document(record, now)
        except Exception as e:
            logger.warning("Mapping error: %s", e)
            errors += 1
            continue

        batch.append(doc)
        total += 1

        if len(batch) >= batch_size:
            inserted += await upsert_batch(db, batch)
            batch.clear()
            if total % 50_000 == 0:
                logger.info("  %d processed, %d new …", total, inserted)

    if batch:
        inserted += await upsert_batch(db, batch)

    await mongodb.disconnect()
    logger.info(
        "Import complete — total: %d, inserted: %d, errors: %d",
        total, inserted, errors,
    )
    return {"total": total, "inserted": inserted, "errors": errors}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

DEFAULT_SOURCE = os.path.expanduser(
    "~/dev/advandeb_auxiliary/abstracts_reproduction/data_full"
)


def main():
    parser = argparse.ArgumentParser(
        description="Import OpenAlex abstracts into the documents collection."
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"Directory containing works.jsonl / abstracts.jsonl (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--mode",
        choices=["works", "abstracts"],
        default="works",
        help="Input file: 'works' = works.jsonl (full metadata), "
             "'abstracts' = abstracts.jsonl (lighter, pre-built abstract text). "
             "Default: works",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of records to import (default: all)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BULK_SIZE,
        help=f"Documents per bulk_write call (default: {BULK_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse records and show samples without writing to DB",
    )
    args = parser.parse_args()

    asyncio.run(
        run_import(
            source_dir=args.source,
            mode=args.mode,
            limit=args.limit,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
        )
    )


if __name__ == "__main__":
    main()
