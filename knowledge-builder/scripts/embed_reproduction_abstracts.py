"""
Embed the imported *reproduction* abstracts so the chat can retrieve them.

Chat retrieval (``hybrid_search``) only searches the chunk/vector index, never
the ``documents`` collection. The reproduction abstracts were imported as
``documents`` with no chunks/embeddings, so chat currently can't see them. This
script chunks + embeds each abstract and writes it to BOTH stores:

  - **ChromaDB** (``advandeb_chunks``)        → vector search
  - **ArangoDB** ``chunks`` + ``chunk_belongs_to`` → keyword full-text + provenance

Chunks are tagged ``general_domain='reproduction'`` so retrieval can optionally
scope to the reproduction domain (HybridRetrievalService ``domain_filter``).

Selection: documents with ``general_domain=='reproduction'`` and
``embedding_status != 'embedded'``. Idempotent + resumable — the doc's
``embedding_status`` flips to ``embedded`` only after its chunks are written, and
chunk writes use ``on_duplicate='ignore'`` / Chroma upsert, so re-running never
duplicates. Runs independently of the fact-extraction job.

Run in the background (force CPU so it doesn't contend with the Ollama GPU job):

    cd /home/adeb/dev/advandeb && set -a && . app/backend/.env && set +a
    nohup env CUDA_VISIBLE_DEVICES="" conda run -n advandeb python \\
        knowledge-builder/scripts/embed_reproduction_abstracts.py \\
        > /tmp/repro_embed.log 2>&1 &
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.config.settings import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("repro_embed")

GENERAL_DOMAIN = "reproduction"


def _aql_retry(a, query: str, binds: Dict[str, Any], attempts: int = 6) -> bool:
    """Run an UPDATE AQL with retry/backoff. The fact-extraction job updates the
    same documents concurrently → lock-wait timeouts (HTTP 409); retry rather than
    crash. On persistent failure the doc is left for a later pass (chunk writes are
    idempotent, so re-embedding is safe)."""
    for i in range(attempts):
        try:
            a.aql(query, binds)
            return True
        except Exception as exc:  # noqa: BLE001
            if i == attempts - 1:
                logger.warning("doc status update failed after %d tries: %s", attempts, str(exc)[:120])
                return False
            time.sleep(0.4 * (i + 1))
    return False


def ensure_index(a) -> None:
    col = a.db.collection("documents")
    existing = [idx["fields"] for idx in col.indexes()]
    if ["embedding_status"] not in existing:
        try:
            col.add_persistent_index(fields=["embedding_status"], sparse=False)
            logger.info("Created index on documents[embedding_status]")
        except Exception as exc:  # noqa: BLE001
            logger.warning("index create skipped: %s", exc)


def embed_batch_docs(docs, chunker, embedder, chroma, a, dry_run) -> Dict[str, int]:
    """Chunk+embed a batch of documents; write to Chroma + Arango. Returns counters."""
    chunk_objs = []          # (doc, chunk)
    no_text_keys: List[str] = []
    for d in docs:
        text = (d.get("content") or d.get("abstract") or "").strip()
        if not text:
            no_text_keys.append(d["_key"])
            continue
        for c in chunker.chunk_document(text, document_id=d["_key"]):
            chunk_objs.append((d, c))

    if dry_run:
        return {"docs": len(docs), "chunks": len(chunk_objs), "no_text": len(no_text_keys),
                "embedded_docs": 0}

    now = datetime.now(timezone.utc).isoformat()

    # Mark empty docs so they aren't retried forever.
    if no_text_keys:
        _aql_retry(a, "FOR k IN @ks FOR d IN documents FILTER d._key==k "
                   "UPDATE d WITH {embedding_status:'no_text', updated_at:@t} IN documents "
                   "OPTIONS {ignoreErrors:true}", {"ks": no_text_keys, "t": now})

    embedded_keys = sorted({d["_key"] for d, _ in chunk_objs})
    if chunk_objs:
        texts = [c.text for _, c in chunk_objs]
        embeddings = embedder.embed_batch(texts, show_progress=False)

        # ChromaDB (vector)
        chroma.add_chunks_batch(
            chunk_ids=[c.chunk_id for _, c in chunk_objs],
            texts=texts,
            embeddings=embeddings,
            metadatas=[_chroma_meta(d, c) for d, c in chunk_objs],
        )

        # ArangoDB chunks + chunk_belongs_to edges
        a.db.collection("chunks").import_bulk(
            [_arango_chunk(d, c) for d, c in chunk_objs],
            on_duplicate="ignore", halt_on_error=False)
        a.db.collection("chunk_belongs_to").import_bulk(
            [{"_key": f"{c.chunk_id}_belongs",
              "_from": f"chunks/{c.chunk_id}", "_to": f"documents/{d['_key']}"}
             for d, c in chunk_objs],
            on_duplicate="ignore", halt_on_error=False)

        # Mark docs embedded (count chunks per doc)
        per_doc: Dict[str, int] = {}
        for d, _ in chunk_objs:
            per_doc[d["_key"]] = per_doc.get(d["_key"], 0) + 1
        _aql_retry(a, "FOR k IN ATTRIBUTES(@counts) FOR d IN documents FILTER d._key==k "
                   "UPDATE d WITH {embedding_status:'embedded', num_chunks:@counts[k], updated_at:@t} "
                   "IN documents OPTIONS {ignoreErrors:true}", {"counts": per_doc, "t": now})

    return {"docs": len(docs), "chunks": len(chunk_objs), "no_text": len(no_text_keys),
            "embedded_docs": len(embedded_keys)}


def _chroma_meta(d: Dict[str, Any], c) -> Dict[str, Any]:
    meta = c.to_chromadb_metadata()
    meta["document_id"] = d["_key"]
    meta["general_domain"] = GENERAL_DOMAIN
    meta["title"] = d.get("title", "") or ""
    meta["year"] = int(d.get("year") or 0)
    meta["doi"] = d.get("doi", "") or ""
    meta["source_path"] = d.get("source_path", "") or ""
    return meta


def _arango_chunk(d: Dict[str, Any], c) -> Dict[str, Any]:
    return {
        "_key": c.chunk_id,
        "document_id": d["_key"],
        "chunk_index": getattr(c, "chunk_index", 0),
        "text": c.text,
        "char_start": getattr(c, "char_start", None),
        "char_end": getattr(c, "char_end", None),
        "general_domain": GENERAL_DOMAIN,
    }


def run(limit: int, batch_size: int, dry_run: bool) -> None:
    from advandeb_kb.database.arango_client import ArangoDatabase
    from advandeb_kb.services.chunking_service import ChunkingService
    from advandeb_kb.services.embedding_service import EmbeddingService
    from advandeb_kb.services.chromadb_service import ChromaDBService

    a = ArangoDatabase()
    a.connect()
    ensure_index(a)

    pending = a.aql(
        "RETURN LENGTH(FOR d IN documents FILTER d.general_domain==@g "
        "AND d.embedding_status != 'embedded' RETURN 1)", {"g": GENERAL_DOMAIN})[0]
    logger.info("reproduction docs needing embedding: %d (limit=%s, dry_run=%s)",
                pending, limit or "all", dry_run)
    if pending == 0:
        logger.info("Nothing to embed.")
        return

    chunker = ChunkingService(chunk_size=512, overlap=128)
    embedder = EmbeddingService()
    chroma = ChromaDBService()
    logger.info("embedding model=%s | ChromaDB current vectors=%d",
                settings.EMBEDDING_MODEL, chroma.count())

    tot = {"docs": 0, "chunks": 0, "no_text": 0, "embedded_docs": 0}
    start = time.time()
    unlimited = (limit == 0)
    remaining = limit if limit else pending

    while unlimited or remaining > 0:
        take = batch_size if unlimited else min(batch_size, remaining)
        docs = a.aql(
            "FOR d IN documents FILTER d.general_domain==@g AND d.embedding_status != 'embedded' "
            "LIMIT @n RETURN d", {"g": GENERAL_DOMAIN, "n": take})
        if not docs:
            break
        r = embed_batch_docs(docs, chunker, embedder, chroma, a, dry_run)
        for k in tot:
            tot[k] += r[k]
        el = time.time() - start
        rate = tot["docs"] / el if el else 0
        logger.info("progress: docs=%d chunks=%d no_text=%d embedded=%d (%.1f docs/s)",
                    tot["docs"], tot["chunks"], tot["no_text"], tot["embedded_docs"], rate)
        if not unlimited:
            remaining -= len(docs)
        if dry_run:
            break

    logger.info("DONE — docs=%d chunks=%d no_text=%d embedded=%d in %.1fs | ChromaDB vectors=%d",
                tot["docs"], tot["chunks"], tot["no_text"], tot["embedded_docs"],
                time.time() - start, chroma.count() if not dry_run else -1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, default=0, help="Max docs this run (0=all)")
    p.add_argument("--batch-size", type=int, default=256, help="Docs per embed batch")
    p.add_argument("--dry-run", action="store_true", help="Count + chunk one batch, write nothing")
    args = p.parse_args()
    run(args.limit, args.batch_size, args.dry_run)


if __name__ == "__main__":
    main()
