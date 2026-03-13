#!/usr/bin/env python3
"""
ingest_test_arango.py — Ingest test PDFs into ChromaDB + ArangoDB.

Reads the list from test_pdfs_week11.txt (relative to repo root),
extracts text from each PDF, chunks it, generates embeddings, and
stores chunks in both ChromaDB (vector search) and ArangoDB (graph).

Usage:
    # Ingest the 75 test PDFs:
    conda run -n advandeb python knowledge-builder/scripts/ingest_test_arango.py

    # Custom PDF list:
    conda run -n advandeb python knowledge-builder/scripts/ingest_test_arango.py \
        --pdf-list /path/to/list.txt

    # Dry run (no writes):
    conda run -n advandeb python knowledge-builder/scripts/ingest_test_arango.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
import time
from pathlib import Path

# Allow running from repo root without installing
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("ingest_test")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PDF_LIST = REPO_ROOT / "test_pdfs_week11.txt"


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def extract_pdf_text(pdf_path: str) -> str:
    """Extract all text from a PDF file using pypdf."""
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


def doc_id_from_path(pdf_path: str) -> str:
    """Deterministic document ID from file path."""
    return "doc_" + hashlib.sha1(pdf_path.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Main ingestion logic
# ---------------------------------------------------------------------------

def ingest_pdf(
    pdf_path: str,
    chunker,
    embedder,
    chroma,
    arango,
    dry_run: bool,
) -> dict:
    """Process a single PDF: extract → chunk → embed → store. Returns stats."""
    t0 = time.time()
    doc_id = doc_id_from_path(pdf_path)
    filename = os.path.basename(pdf_path)

    # ---- Extract text ----
    text = extract_pdf_text(pdf_path)
    if not text:
        logger.warning("No text extracted from %s — skipping", filename)
        return {"path": pdf_path, "status": "skipped", "chunks": 0}

    # ---- Chunk ----
    chunks = chunker.chunk_document(text, doc_id)
    if not chunks:
        logger.warning("No chunks produced for %s — skipping", filename)
        return {"path": pdf_path, "status": "skipped", "chunks": 0}

    if dry_run:
        logger.info("[DRY] %s → %d chunks (would store)", filename, len(chunks))
        return {"path": pdf_path, "status": "dry", "chunks": len(chunks)}

    # ---- Store document record in ArangoDB ----
    arango_doc = {
        "_key": doc_id,
        "title": filename.replace(".pdf", ""),
        "source_path": pdf_path,
        "source_type": "pdf",
        "processing_status": "ingested",
        "char_count": len(text),
        "chunk_count": len(chunks),
    }
    arango.upsert("documents", arango_doc)

    # ---- Embed + store chunks ----
    texts = [c.text for c in chunks]
    embeddings = embedder.embed_batch(texts, batch_size=64, show_progress=False)

    chunk_ids = [c.chunk_id for c in chunks]
    metadatas = [c.to_chromadb_metadata() for c in chunks]

    # Add source_path to each chunk metadata for retrieval traceability
    for meta in metadatas:
        meta["source_path"] = pdf_path

    chroma.add_chunks_batch(chunk_ids, texts, embeddings, metadatas)

    # ---- Store chunk records in ArangoDB ----
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
        # chunk → document edge
        edge = {
            "_key": f"{chunk.chunk_id}_belongs",
            "_from": f"chunks/{chunk.chunk_id}",
            "_to": f"documents/{doc_id}",
        }
        arango.upsert("chunk_belongs_to", edge)

    elapsed = time.time() - t0
    logger.info(
        "Ingested %s: %d chunks in %.1fs (doc_id=%s)",
        filename, len(chunks), elapsed, doc_id,
    )
    return {"path": pdf_path, "status": "ok", "chunks": len(chunks), "doc_id": doc_id}


def main():
    parser = argparse.ArgumentParser(description="Ingest test PDFs into ChromaDB + ArangoDB")
    parser.add_argument(
        "--pdf-list",
        default=str(DEFAULT_PDF_LIST),
        help=f"Path to newline-separated PDF list (default: {DEFAULT_PDF_LIST})",
    )
    parser.add_argument("--dry-run", action="store_true", help="No writes — just count chunks")
    parser.add_argument(
        "--chunk-size", type=int, default=512, help="Characters per chunk (default 512)"
    )
    parser.add_argument(
        "--overlap", type=int, default=128, help="Overlap characters (default 128)"
    )
    args = parser.parse_args()

    # ---- Load PDF list ----
    pdf_list_path = Path(args.pdf_list)
    if not pdf_list_path.exists():
        logger.error("PDF list not found: %s", pdf_list_path)
        sys.exit(1)

    pdf_paths = [
        line.strip()
        for line in pdf_list_path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    logger.info("Loaded %d PDF paths from %s", len(pdf_paths), pdf_list_path)

    # ---- Init services ----
    from advandeb_kb.services.chunking_service import ChunkingService
    from advandeb_kb.services.embedding_service import EmbeddingService
    from advandeb_kb.services.chromadb_service import ChromaDBService
    from advandeb_kb.database.arango_client import ArangoDatabase

    chunker = ChunkingService(chunk_size=args.chunk_size, overlap=args.overlap)
    embedder = EmbeddingService()
    chroma = ChromaDBService()

    arango = ArangoDatabase()
    if not args.dry_run:
        arango.connect()
        arango.setup_schema()

    # ---- Ingest ----
    stats = {"ok": 0, "skipped": 0, "error": 0, "total_chunks": 0}
    for i, pdf_path in enumerate(pdf_paths, 1):
        logger.info("[%d/%d] %s", i, len(pdf_paths), os.path.basename(pdf_path))
        try:
            result = ingest_pdf(pdf_path, chunker, embedder, chroma, arango, args.dry_run)
            stats[result["status"] if result["status"] in stats else "ok"] += 1
            stats["total_chunks"] += result.get("chunks", 0)
        except Exception as exc:
            logger.error("Error ingesting %s: %s", pdf_path, exc)
            stats["error"] += 1

    logger.info(
        "=== Ingestion Complete === ok=%d skipped=%d error=%d total_chunks=%d",
        stats["ok"], stats["skipped"], stats["error"], stats["total_chunks"],
    )
    if not args.dry_run and not args.dry_run:
        try:
            logger.info("ArangoDB stats: %s", arango.stats())
        except Exception:
            pass


if __name__ == "__main__":
    main()
