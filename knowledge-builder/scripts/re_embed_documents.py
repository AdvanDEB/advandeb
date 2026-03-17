#!/usr/bin/env python3
"""
Re-embed all documents that have text content but are missing from ChromaDB.

Targets documents in the 'advandeb' MongoDB database where:
  - content is non-empty
  - embedding_status is NOT "embedded"

This recovers the ~1,183 documents that were processed through the old
pipeline.py path (text extraction + facts + SF matching) but never had
their chunks embedded into ChromaDB.

Usage:
    # Dry run — shows counts without writing anything
    python scripts/re_embed_documents.py --dry-run

    # Embed all un-embedded documents (default, concurrency 4)
    python scripts/re_embed_documents.py

    # Limit batch size and concurrency
    python scripts/re_embed_documents.py --limit 100 --concurrency 2

    # Re-embed even documents already marked embedded (force mode)
    python scripts/re_embed_documents.py --force

Environment (loaded from dev-server/.env):
    MONGODB_URL, DATABASE_NAME, CHROMA_PERSIST_DIR, CHROMA_COLLECTION,
    EMBEDDING_MODEL

Progress is logged to stdout. The script is safe to re-run — ChromaDB
upserts are idempotent, and --skip-existing (default) avoids redundant work.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Allow running from repo root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev-server"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / "dev-server" / ".env")

from advandeb_kb.config.settings import settings
from advandeb_kb.services.chunking_service import ChunkingService
from advandeb_kb.services.embedding_service import EmbeddingService
from advandeb_kb.services.chromadb_service import ChromaDBService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("re_embed")


# ---------------------------------------------------------------------------
# Core embedding logic (sync — called from executor)
# ---------------------------------------------------------------------------

def embed_document(
    doc: dict,
    chunker: ChunkingService,
    embedder: EmbeddingService,
    chroma: ChromaDBService,
) -> int:
    """
    Chunk and embed a single document into ChromaDB.

    Returns the number of chunks embedded (0 if skipped/failed).
    """
    doc_id = str(doc["_id"])
    text = doc.get("content") or doc.get("abstract") or ""
    if not text.strip():
        return 0

    chunks = chunker.chunk_document(text, document_id=doc_id)
    if not chunks:
        return 0

    metadatas = []
    for chunk in chunks:
        meta = chunk.to_chromadb_metadata()
        meta["title"] = doc.get("title", "") or ""
        meta["year"] = int(doc.get("year") or 0)
        meta["doi"] = doc.get("doi", "") or ""
        meta["general_domain"] = doc.get("general_domain", "") or ""
        meta["source_path"] = doc.get("source_path", "") or ""
        metadatas.append(meta)

    texts = [c.text for c in chunks]
    embeddings = embedder.embed_batch(texts, show_progress=False)

    chroma.add_chunks_batch(
        chunk_ids=[c.chunk_id for c in chunks],
        texts=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(chunks)


# ---------------------------------------------------------------------------
# Async worker pool
# ---------------------------------------------------------------------------

async def process_batch(
    docs: list[dict],
    chunker: ChunkingService,
    embedder: EmbeddingService,
    chroma: ChromaDBService,
    db,
    concurrency: int,
    dry_run: bool,
) -> tuple[int, int, int]:
    """
    Process a list of documents with bounded concurrency.

    Returns (embedded_count, skipped_count, failed_count).
    """
    sem = asyncio.Semaphore(concurrency)
    loop = asyncio.get_event_loop()

    embedded = skipped = failed = 0

    async def process_one(doc: dict) -> None:
        nonlocal embedded, skipped, failed
        doc_id = str(doc["_id"])

        async with sem:
            if dry_run:
                text = doc.get("content") or doc.get("abstract") or ""
                if text.strip():
                    embedded += 1
                else:
                    skipped += 1
                return

            try:
                chunk_count = await loop.run_in_executor(
                    None, embed_document, doc, chunker, embedder, chroma
                )

                if chunk_count == 0:
                    skipped += 1
                    # Still mark as attempted so we don't retry empty docs
                    await db.documents.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {
                            "embedding_status": "no_text",
                            "updated_at": datetime.utcnow(),
                        }},
                    )
                    logger.debug("Skip (no text): %s", doc_id)
                else:
                    embedded += 1
                    await db.documents.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {
                            "embedding_status": "embedded",
                            "num_chunks": chunk_count,
                            "updated_at": datetime.utcnow(),
                        }},
                    )
                    logger.debug("Embedded %d chunks: %s", chunk_count, doc_id)

            except Exception as exc:
                failed += 1
                logger.warning("Failed to embed %s: %s", doc_id, exc)
                try:
                    await db.documents.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {
                            "embedding_status": "failed",
                            "updated_at": datetime.utcnow(),
                        }},
                    )
                except Exception:
                    pass

    await asyncio.gather(*[process_one(d) for d in docs])
    return embedded, skipped, failed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main_async(args: argparse.Namespace) -> None:
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.DATABASE_NAME]

    # Build query
    if args.force:
        # Re-embed everything with content, regardless of current status
        query: dict = {"content": {"$nin": [None, ""]}}
    else:
        # Only docs not yet embedded
        query = {
            "content": {"$nin": [None, ""]},
            "embedding_status": {"$nin": ["embedded"]},
        }

    total = await db.documents.count_documents(query)
    already_embedded = await db.documents.count_documents({"embedding_status": "embedded"})
    logger.info(
        "Database: %s | total docs: %d | already embedded: %d | to process: %d",
        settings.DATABASE_NAME,
        await db.documents.count_documents({}),
        already_embedded,
        total,
    )

    if total == 0:
        logger.info("Nothing to embed. All documents are already embedded.")
        return

    if args.dry_run:
        logger.info("DRY RUN — would embed up to %d documents. No changes written.", total)
        return

    # Initialise services (model load happens lazily on first embed call)
    logger.info("Initialising embedding services (model: %s)…", settings.EMBEDDING_MODEL)
    chunker = ChunkingService(chunk_size=512, overlap=128)
    embedder = EmbeddingService()
    chroma = ChromaDBService()

    logger.info(
        "ChromaDB: %s | current vector count: %d",
        settings.CHROMA_PERSIST_DIR,
        chroma.count(),
    )

    # Stream documents in batches to avoid loading everything into RAM
    limit = args.limit if args.limit else total
    page_size = min(args.page_size, limit)
    processed = 0
    total_embedded = total_skipped = total_failed = 0
    start_time = time.monotonic()

    logger.info(
        "Starting re-embed: limit=%d page_size=%d concurrency=%d",
        limit, page_size, args.concurrency,
    )

    cursor = db.documents.find(query).limit(limit)
    page: list[dict] = []

    async for doc in cursor:
        page.append(doc)
        if len(page) >= page_size:
            emb, skp, fail = await process_batch(
                page, chunker, embedder, chroma, db, args.concurrency, dry_run=False
            )
            total_embedded += emb
            total_skipped += skp
            total_failed += fail
            processed += len(page)

            elapsed = time.monotonic() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (limit - processed) / rate if rate > 0 else 0
            logger.info(
                "[%d/%d] embedded=%d skipped=%d failed=%d  rate=%.1f docs/min  ETA=%.0fs",
                processed, limit,
                total_embedded, total_skipped, total_failed,
                rate * 60, eta,
            )
            page = []

    # Flush remaining
    if page:
        emb, skp, fail = await process_batch(
            page, chunker, embedder, chroma, db, args.concurrency, dry_run=False
        )
        total_embedded += emb
        total_skipped += skp
        total_failed += fail
        processed += len(page)

    elapsed = time.monotonic() - start_time
    final_count = chroma.count()

    logger.info(
        "\n=== Re-embed complete ===\n"
        "  Documents processed : %d\n"
        "  Chunks embedded     : (see ChromaDB count below)\n"
        "  Docs with new embeds: %d\n"
        "  Docs skipped (no txt): %d\n"
        "  Docs failed         : %d\n"
        "  Elapsed             : %.1fs\n"
        "  ChromaDB total vecs : %d",
        processed,
        total_embedded,
        total_skipped,
        total_failed,
        elapsed,
        final_count,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-embed un-embedded documents from MongoDB into ChromaDB"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count documents to process without writing anything",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed even documents already marked as embedded (re-indexing)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of documents to process (0 = all)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=50,
        help="Documents fetched per MongoDB page (default: 50)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Number of documents embedded in parallel (default: 4)",
    )
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
