#!/usr/bin/env python3
"""
batch_ingest_production.py — Production ingestion of all PDFs into ChromaDB + ArangoDB.

Features:
  - Multiprocessing: configurable worker count (default 8)
  - Checkpointing: skips already-ingested docs (keyed on doc_id)
  - GPU acceleration: EmbeddingService uses all 3x Quadro RTX 8000
  - Progress reporting: logs throughput every N docs
  - Fault-tolerant: per-doc error isolation, logs failures to a skip file

Usage:
    # Production run (all 1,306 PDFs, 8 workers):
    conda run -n advandeb python scripts/batch_ingest_production.py

    # Custom workers:
    conda run -n advandeb python scripts/batch_ingest_production.py --workers 4

    # Dry run (no writes, just count chunks):
    conda run -n advandeb python scripts/batch_ingest_production.py --dry-run

    # Re-ingest specific PDFs (bypass checkpoint):
    conda run -n advandeb python scripts/batch_ingest_production.py --force

Logs:
    ingestion_prod.log    — main log
    ingestion_errors.txt  — PDFs that failed (rerun with --error-list)

Nohup (background):
    nohup conda run -n advandeb python scripts/batch_ingest_production.py \\
        --workers 8 > ingestion_prod.log 2>&1 &
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Use cached models — avoid slow HuggingFace network checks
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

# Allow running from repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "knowledge-builder"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(process)d %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("batch_ingest")

PAPERS_DIR = REPO_ROOT / "papers"
CHECKPOINT_FILE = REPO_ROOT / "ingestion_checkpoint.txt"
ERRORS_FILE = REPO_ROOT / "ingestion_errors.txt"

# Embedding batch size per GPU call
EMBED_BATCH_SIZE = 128


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def doc_id_from_path(pdf_path: str) -> str:
    return "doc_" + hashlib.sha1(pdf_path.encode()).hexdigest()[:16]


def extract_pdf_text(pdf_path: str) -> str:
    try:
        from pypdf import PdfReader
        text = ""
        with open(pdf_path, "rb") as f:
            reader = PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() or ""
        return text.strip()
    except Exception as exc:
        logger.warning("pypdf failed for %s: %s — trying pdfminer", pdf_path, exc)
        try:
            from pdfminer.high_level import extract_text as pdfminer_extract
            return pdfminer_extract(pdf_path).strip()
        except Exception as exc2:
            logger.error("All extractors failed for %s: %s", pdf_path, exc2)
            return ""


def load_checkpoint() -> set[str]:
    """Return set of already-ingested doc_ids."""
    if not CHECKPOINT_FILE.exists():
        return set()
    lines = CHECKPOINT_FILE.read_text().splitlines()
    return {ln.strip() for ln in lines if ln.strip()}


def append_checkpoint(doc_id: str) -> None:
    with CHECKPOINT_FILE.open("a") as f:
        f.write(doc_id + "\n")


def append_error(pdf_path: str, reason: str) -> None:
    with ERRORS_FILE.open("a") as f:
        f.write(f"{pdf_path}\t{reason}\n")


# ---------------------------------------------------------------------------
# Per-document ingestion (runs in worker process)
# ---------------------------------------------------------------------------

_worker_services: dict = {}


def _init_worker(chunk_size: int, overlap: int, dry_run: bool = False) -> None:
    """Initializer for each worker process — loads heavy services once."""
    global _worker_services
    from advandeb_kb.services.chunking_service import ChunkingService

    _worker_services["chunk_size"] = chunk_size
    _worker_services["overlap"] = overlap
    _worker_services["dry_run"] = dry_run
    _worker_services["chunker"] = ChunkingService(chunk_size=chunk_size, overlap=overlap)

    if dry_run:
        # Dry-run: only need chunker to count chunks
        return

    # CRITICAL ORDER: ChromaDB (onnxruntime) and ArangoDB MUST connect before
    # PyTorch/sentence-transformers is imported. Loading PyTorch first causes a
    # segfault when ChromaDB's PersistentClient tries to open the SQLite WAL.
    from advandeb_kb.services.chromadb_service import ChromaDBService
    from advandeb_kb.database.arango_client import ArangoDatabase

    _worker_services["chroma"] = ChromaDBService()
    _worker_services["chroma"]._ensure_connected()  # connect before torch loads

    _worker_services["arango"] = ArangoDatabase()
    _worker_services["arango"].connect()

    # Now safe to load PyTorch + sentence-transformers
    import torch
    from advandeb_kb.services.embedding_service import EmbeddingService

    # Assign GPU by worker index (round-robin across 3 GPUs)
    worker_idx = int(mp.current_process().name.split("-")[-1]) - 1 if "-" in mp.current_process().name else 0
    gpu_id = worker_idx % 3
    if torch.cuda.is_available():
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
        logger.info("Worker %s assigned GPU %d", mp.current_process().name, gpu_id)

    _worker_services["embedder"] = EmbeddingService()


def _ingest_one(args: tuple) -> dict:
    """Ingest a single PDF. Called in worker process."""
    pdf_path, dry_run = args
    doc_id = doc_id_from_path(pdf_path)
    filename = os.path.basename(pdf_path)
    t0 = time.time()

    try:
        chunker = _worker_services["chunker"]

        text = extract_pdf_text(pdf_path)
        if not text:
            return {"path": pdf_path, "doc_id": doc_id, "status": "skipped", "chunks": 0, "reason": "no_text"}

        chunks = chunker.chunk_document(text, doc_id)
        if not chunks:
            return {"path": pdf_path, "doc_id": doc_id, "status": "skipped", "chunks": 0, "reason": "no_chunks"}

        if dry_run:
            logger.info("[DRY] %s → %d chunks", filename, len(chunks))
            return {"path": pdf_path, "doc_id": doc_id, "status": "dry", "chunks": len(chunks)}

        embedder = _worker_services["embedder"]
        chroma = _worker_services["chroma"]
        arango = _worker_services["arango"]

        # Store document in ArangoDB
        arango_doc = {
            "_key": doc_id,
            "title": filename.replace(".pdf", ""),
            "source_path": str(pdf_path),
            "source_type": "pdf",
            "processing_status": "ingested",
            "char_count": len(text),
            "chunk_count": len(chunks),
        }
        arango.upsert("documents", arango_doc)

        # Embed all chunks (GPU batch) — sanitize texts to remove invalid Unicode
        def _sanitize(t: object) -> str:
            if not isinstance(t, str) or not t:
                return " "
            # Replace lone surrogates and other non-encodable chars
            return t.encode("utf-8", errors="replace").decode("utf-8", errors="replace").strip() or " "

        texts = [_sanitize(c.text) for c in chunks]
        embeddings = embedder.embed_batch(texts, batch_size=EMBED_BATCH_SIZE, show_progress=False)

        # Store in ChromaDB
        chunk_ids = [c.chunk_id for c in chunks]
        metadatas = [c.to_chromadb_metadata() for c in chunks]
        for meta in metadatas:
            meta["source_path"] = str(pdf_path)
        chroma.add_chunks_batch(chunk_ids, texts, embeddings, metadatas)

        # Store chunks + edges in ArangoDB
        for chunk, emb in zip(chunks, embeddings):
            chunk_doc = {
                "_key": chunk.chunk_id,
                "document_id": doc_id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
            }
            arango.upsert("chunks", chunk_doc)
            edge = {
                "_key": f"{chunk.chunk_id}_belongs",
                "_from": f"chunks/{chunk.chunk_id}",
                "_to": f"documents/{doc_id}",
            }
            arango.upsert("chunk_belongs_to", edge)

        elapsed = time.time() - t0
        logger.info("OK %s: %d chunks in %.1fs", filename, len(chunks), elapsed)
        return {"path": pdf_path, "doc_id": doc_id, "status": "ok", "chunks": len(chunks)}

    except Exception as exc:
        logger.error("ERROR %s: %s", filename, exc, exc_info=True)
        return {"path": pdf_path, "doc_id": doc_id, "status": "error", "chunks": 0, "reason": str(exc)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Production batch PDF ingestion")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers (default 8)")
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--overlap", type=int, default=128)
    parser.add_argument("--dry-run", action="store_true", help="No writes")
    parser.add_argument("--force", action="store_true", help="Ignore checkpoint, re-ingest all")
    parser.add_argument(
        "--pdf-dir", default=str(PAPERS_DIR),
        help=f"Directory of PDFs (default {PAPERS_DIR})"
    )
    parser.add_argument(
        "--error-list", default=None,
        help="Re-run only PDFs listed in this file (tab-separated, path is first column)"
    )
    args = parser.parse_args()

    # Collect PDFs
    if args.error_list:
        lines = Path(args.error_list).read_text().splitlines()
        all_pdfs = [ln.split("\t")[0].strip() for ln in lines if ln.strip()]
        logger.info("Error re-run mode: %d PDFs from %s", len(all_pdfs), args.error_list)
    else:
        all_pdfs = sorted(str(p) for p in Path(args.pdf_dir).rglob("*.pdf"))
        logger.info("Found %d PDFs in %s", len(all_pdfs), args.pdf_dir)

    # Apply checkpoint
    if not args.force and not args.dry_run:
        done = load_checkpoint()
        pending = [p for p in all_pdfs if doc_id_from_path(p) not in done]
        skipped_count = len(all_pdfs) - len(pending)
        if skipped_count:
            logger.info("Checkpoint: skipping %d already-ingested PDFs, %d remaining", skipped_count, len(pending))
    else:
        pending = all_pdfs
        if args.force:
            logger.info("--force: re-ingesting all %d PDFs", len(pending))

    if not pending:
        logger.info("Nothing to do — all PDFs already ingested.")
        return

    logger.info(
        "Starting ingestion: %d PDFs, %d workers, chunk_size=%d, overlap=%d, dry_run=%s",
        len(pending), args.workers, args.chunk_size, args.overlap, args.dry_run,
    )

    stats = {"ok": 0, "skipped": 0, "error": 0, "total_chunks": 0}
    t_start = time.time()

    work_items = [(p, args.dry_run) for p in pending]

    if args.workers == 1:
        # Single-process mode (easier debugging)
        _init_worker(args.chunk_size, args.overlap, dry_run=args.dry_run)
        for i, item in enumerate(work_items, 1):
            result = _ingest_one(item)
            _update_stats(stats, result, i, len(pending), t_start, args.dry_run)
    else:
        ctx = mp.get_context("spawn")
        with ctx.Pool(
            processes=args.workers,
            initializer=_init_worker,
            initargs=(args.chunk_size, args.overlap, args.dry_run),
        ) as pool:
            for i, result in enumerate(pool.imap_unordered(_ingest_one, work_items), 1):
                _update_stats(stats, result, i, len(pending), t_start, args.dry_run)

    elapsed = time.time() - t_start
    logger.info(
        "=== Ingestion Complete === ok=%d skipped=%d error=%d total_chunks=%d elapsed=%.0fs",
        stats["ok"], stats["skipped"], stats["error"], stats["total_chunks"], elapsed,
    )
    if stats["error"]:
        logger.warning("Failed PDFs logged to %s — rerun with --error-list %s", ERRORS_FILE, ERRORS_FILE)

    # Final ArangoDB stats
    if not args.dry_run:
        try:
            from advandeb_kb.database.arango_client import ArangoDatabase
            db = ArangoDatabase()
            db.connect()
            logger.info("ArangoDB stats: %s", db.stats())
        except Exception as exc:
            logger.warning("Could not get ArangoDB stats: %s", exc)


def _update_stats(stats: dict, result: dict, i: int, total: int, t_start: float, dry_run: bool) -> None:
    status = result.get("status", "error")
    if status in ("ok", "dry"):
        stats["ok"] += 1
        if not dry_run:
            append_checkpoint(result["doc_id"])
    elif status == "skipped":
        stats["skipped"] += 1
    else:
        stats["error"] += 1
        append_error(result["path"], result.get("reason", "unknown"))

    stats["total_chunks"] += result.get("chunks", 0)

    # Progress every 10 docs
    if i % 10 == 0 or i == total:
        elapsed = time.time() - t_start
        rate = i / elapsed if elapsed > 0 else 0
        eta = (total - i) / rate if rate > 0 else 0
        logger.info(
            "Progress: %d/%d (%.0f%%) — %.1f docs/s — ETA %.0fs — chunks so far: %d",
            i, total, 100 * i / total, rate, eta, stats["total_chunks"],
        )


if __name__ == "__main__":
    main()
