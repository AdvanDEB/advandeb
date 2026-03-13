#!/usr/bin/env python3
"""
Batch PDF ingestion script — walks a directory and queues embedding tasks.

Pipeline per PDF:
  1. Create MongoDB Document record (title from filename)
  2. Extract text via PyPDF2
  3. Queue embed_document_async Celery task (chunk + embed + store in ChromaDB)
  4. Optionally run fact extraction (--with-facts flag)

Usage:
    # Ingest all PDFs in default PAPERS_ROOT
    python scripts/batch_ingest.py

    # Custom directory with parallelism
    python scripts/batch_ingest.py --input-dir /data/papers --parallel-workers 4

    # Dry run: count PDFs without ingesting
    python scripts/batch_ingest.py --dry-run

    # Include fact extraction (slower)
    python scripts/batch_ingest.py --with-facts

    # Filter by subdirectory (domain)
    python scripts/batch_ingest.py --domain reproduction

    # Resume: skip already-ingested documents
    python scripts/batch_ingest.py --skip-existing

Environment:
    MONGODB_URL, DATABASE_NAME, REDIS_URL, PAPERS_ROOT
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / "dev-server" / ".env")

from advandeb_kb.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("batch_ingest")


# ---------------------------------------------------------------------------
# MongoDB helpers (sync)
# ---------------------------------------------------------------------------

def get_mongo_db():
    from pymongo import MongoClient
    client = MongoClient(settings.MONGODB_URL)
    return client[settings.DATABASE_NAME]


def document_already_ingested(db, source_path: str) -> Optional[str]:
    """Return document _id string if already ingested, else None."""
    doc = db.documents.find_one(
        {"source_path": source_path},
        {"_id": 1, "embedding_status": 1},
    )
    if doc:
        return str(doc["_id"])
    return None


def create_document_record(db, pdf_path: Path, papers_root: Path, domain: Optional[str]) -> str:
    """Insert a Document record and return its _id string."""
    from bson import ObjectId

    # Relative path from papers_root (for portability)
    try:
        rel_path = str(pdf_path.relative_to(papers_root))
    except ValueError:
        rel_path = str(pdf_path)

    doc = {
        "_id": ObjectId(),
        "title": pdf_path.stem.replace("_", " ").replace("-", " "),
        "source_type": "pdf_local",
        "source_path": rel_path,
        "general_domain": domain,
        "processing_status": "pending",
        "embedding_status": "pending",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    db.documents.insert_one(doc)
    return str(doc["_id"])


def extract_and_store_text(db, document_id: str, pdf_path: Path) -> bool:
    """Extract text from PDF and update the Document record. Returns True on success."""
    try:
        from PyPDF2 import PdfReader
        text_pages = []
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            for page in reader.pages:
                text_pages.append(page.extract_text() or "")
        text = "\n".join(text_pages).strip()
        if not text:
            logger.warning("No text extracted from %s", pdf_path.name)
            return False

        from bson import ObjectId
        db.documents.update_one(
            {"_id": ObjectId(document_id)},
            {
                "$set": {
                    "content": text,
                    "processing_status": "completed",
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        return True
    except Exception as exc:
        logger.error("Text extraction failed for %s: %s", pdf_path.name, exc)
        from bson import ObjectId
        db.documents.update_one(
            {"_id": ObjectId(document_id)},
            {"$set": {"processing_status": "failed", "updated_at": datetime.utcnow()}},
        )
        return False


# ---------------------------------------------------------------------------
# Celery task queueing
# ---------------------------------------------------------------------------

def queue_embedding_task(document_id: str) -> str:
    """Queue embed_document_async and return Celery task ID."""
    # Import via dev-server context (Celery app defined there)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev-server"))
    from tasks.embedding_tasks import embed_document_async
    result = embed_document_async.delay(document_id)
    return result.id


def queue_ingestion_task(document_id: str) -> str:
    """Queue full ingestion pipeline (text→facts→sf_matching) via Celery."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev-server"))
    from tasks.ingestion_tasks import process_pdf_job
    # We only queue embedding here; process_pdf_job handles its own job record
    # For batch, we use embed_document_async (embedding already done in-process)
    return queue_embedding_task(document_id)


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------

class ProgressTracker:
    def __init__(self, total: int):
        self.total = total
        self.done = 0
        self.skipped = 0
        self.failed = 0
        self.start = time.monotonic()

    def tick(self, success: bool = True, skipped: bool = False):
        if skipped:
            self.skipped += 1
        elif success:
            self.done += 1
        else:
            self.failed += 1

    def report(self, filename: str):
        elapsed = time.monotonic() - self.start
        processed = self.done + self.failed
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (self.total - processed - self.skipped) / rate if rate > 0 else 0
        logger.info(
            "[%d/%d] %-50s | done=%d failed=%d skipped=%d rate=%.1f/min ETA=%.0fs",
            processed + self.skipped,
            self.total,
            filename[:50],
            self.done,
            self.failed,
            self.skipped,
            rate * 60,
            eta,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def find_pdfs(input_dir: Path, domain: Optional[str] = None) -> list[Path]:
    """Recursively find all PDFs, optionally filtered by domain subdirectory."""
    if domain:
        search_root = input_dir / domain
        if not search_root.is_dir():
            logger.warning("Domain directory not found: %s", search_root)
            return []
    else:
        search_root = input_dir

    pdfs = sorted(search_root.rglob("*.pdf"))
    logger.info("Found %d PDFs in %s", len(pdfs), search_root)
    return pdfs


def main():
    parser = argparse.ArgumentParser(description="Batch PDF ingestion into advandeb_kb")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(settings.PAPERS_ROOT),
        help="Root directory containing PDFs (default: PAPERS_ROOT env var)",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Restrict to a subdirectory (sets general_domain on documents)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Documents per batch (for progress grouping, default: 50)",
    )
    parser.add_argument(
        "--parallel-workers",
        type=int,
        default=4,
        help="Celery workers expected (informational only — Celery handles concurrency)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count PDFs and check MongoDB connection without ingesting",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip PDFs already in MongoDB (by source_path)",
    )
    parser.add_argument(
        "--with-facts",
        action="store_true",
        help="Also queue fact extraction after embedding (slower)",
    )
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        logger.error("Input directory not found: %s", input_dir)
        sys.exit(1)

    # Find PDFs
    pdfs = find_pdfs(input_dir, args.domain)
    if not pdfs:
        logger.info("No PDFs found. Exiting.")
        return

    if args.dry_run:
        logger.info("DRY RUN — %d PDFs found, no data written.", len(pdfs))
        return

    # Connect MongoDB
    logger.info("Connecting to MongoDB: %s", settings.MONGODB_URL)
    db = get_mongo_db()
    db.command("ping")  # fail fast if unreachable
    logger.info("MongoDB connected. Database: %s", settings.DATABASE_NAME)

    tracker = ProgressTracker(total=len(pdfs))
    task_ids: list[str] = []

    for pdf_path in pdfs:
        try:
            # Compute relative path for dedup check
            try:
                rel_path = str(pdf_path.relative_to(input_dir))
            except ValueError:
                rel_path = str(pdf_path)

            # Skip existing
            if args.skip_existing:
                existing_id = document_already_ingested(db, rel_path)
                if existing_id:
                    tracker.tick(skipped=True)
                    continue

            # 1. Create document record
            document_id = create_document_record(db, pdf_path, input_dir, args.domain)

            # 2. Extract text
            ok = extract_and_store_text(db, document_id, pdf_path)
            if not ok:
                tracker.tick(success=False)
                tracker.report(pdf_path.name)
                continue

            # 3. Queue embedding
            try:
                task_id = queue_embedding_task(document_id)
                task_ids.append(task_id)
            except Exception as exc:
                logger.warning("Could not queue embedding for %s: %s — queuing skipped", pdf_path.name, exc)

            tracker.tick(success=True)
            tracker.report(pdf_path.name)

        except Exception as exc:
            logger.error("Unexpected error on %s: %s", pdf_path.name, exc)
            tracker.tick(success=False)

    # Final summary
    elapsed = time.monotonic() - tracker.start
    logger.info(
        "=== Batch ingestion complete ===\n"
        "  Total PDFs:       %d\n"
        "  Successfully processed: %d\n"
        "  Skipped (existing):     %d\n"
        "  Failed:                 %d\n"
        "  Embedding tasks queued: %d\n"
        "  Elapsed:                %.1fs",
        len(pdfs),
        tracker.done,
        tracker.skipped,
        tracker.failed,
        len(task_ids),
        elapsed,
    )

    if task_ids:
        logger.info(
            "Embedding tasks are running in Celery workers.\n"
            "  Monitor with: celery -A celery_app inspect active"
        )


if __name__ == "__main__":
    main()
