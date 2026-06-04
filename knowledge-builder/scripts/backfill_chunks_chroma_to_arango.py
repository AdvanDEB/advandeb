#!/usr/bin/env python
"""
Backfill ArangoDB ``chunks`` from the ChromaDB vector store.

Why: retrieval (hybrid_search) returns chunk ids straight from ChromaDB, but the
provenance service (ProvenanceService) only looks chunks up in ArangoDB. The two
stores hold different/partially-disjoint chunk sets, so ~half of chunk citations
resolve to nothing and the UI shows "no provenance".

This copies every ChromaDB chunk into the ArangoDB ``chunks`` collection using the
Chroma id as the document ``_key`` (== ``chunk_id``), so any chunk that retrieval
can cite also exists in the provenance store.

Idempotent: uses ``import_bulk(on_duplicate="ignore")`` — existing chunks are left
untouched, so re-running only adds what is missing.

Usage:
    # dry run (default): read + transform + report, never touches `chunks`
    python scripts/backfill_chunks_chroma_to_arango.py

    # write into the live ArangoDB `chunks` collection
    python scripts/backfill_chunks_chroma_to_arango.py --live

Env (read from app/backend/.env if not already in the environment):
    ARANGO_URL, ARANGO_DB_NAME, ARANGO_USERNAME, ARANGO_PASSWORD
    CHROMA_PERSIST_DIR (default: /home/adeb/dev/advandeb/data/chromadb)
    CHROMA_COLLECTION  (default: advandeb_chunks)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ENV_FILE = Path("/home/adeb/dev/advandeb/app/backend/.env")
CHROMA_PERSIST_DIR_DEFAULT = "/home/adeb/dev/advandeb/data/chromadb"
CHROMA_COLLECTION_DEFAULT = "advandeb_chunks"
BATCH = 5000


def load_env() -> None:
    """Populate os.environ from app/backend/.env without overriding existing vars."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


def get_arango():
    from arango import ArangoClient

    return ArangoClient(hosts=os.environ["ARANGO_URL"]).db(
        os.environ["ARANGO_DB_NAME"],
        username=os.environ["ARANGO_USERNAME"],
        password=os.environ["ARANGO_PASSWORD"],
    )


def get_chroma():
    import chromadb

    persist = os.environ.get("CHROMA_PERSIST_DIR", CHROMA_PERSIST_DIR_DEFAULT)
    name = os.environ.get("CHROMA_COLLECTION", CHROMA_COLLECTION_DEFAULT)
    return chromadb.PersistentClient(path=persist).get_collection(name)


def to_arango_chunk(cid: str, text: str, meta: dict) -> dict:
    meta = meta or {}
    return {
        "_key": cid,
        "chunk_id": cid,
        "document_id": meta.get("document_id"),
        "chunk_index": meta.get("chunk_index"),
        "text": text or "",
        "char_start": meta.get("char_start"),
        "char_end": meta.get("char_end"),
        "source_path": meta.get("source_path"),
        "embedded": True,
        "backfilled_from": "chromadb",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true",
                    help="write into the live ArangoDB `chunks` collection (default: dry run)")
    args = ap.parse_args()

    load_env()
    chroma = get_chroma()
    adb = get_arango()
    chunks = adb.collection("chunks")

    total = chroma.count()
    before = chunks.count()
    mode = "LIVE" if args.live else "DRY RUN"
    print(f"[{mode}] ChromaDB chunks: {total:,} | ArangoDB chunks (before): {before:,}")
    if not args.live:
        print("       (dry run — `chunks` will NOT be modified; pass --live to write)")

    created = ignored = errors = processed = 0
    t0 = time.time()
    offset = 0
    while offset < total:
        got = chroma.get(limit=BATCH, offset=offset, include=["documents", "metadatas"])
        ids = got["ids"]
        if not ids:
            break
        docs = [
            to_arango_chunk(cid, text, meta)
            for cid, text, meta in zip(ids, got["documents"], got["metadatas"])
        ]
        processed += len(docs)
        if args.live:
            res = chunks.import_bulk(docs, on_duplicate="ignore", halt_on_error=False)
            created += res.get("created", 0)
            ignored += res.get("ignored", 0)
            errors += res.get("errors", 0)
        offset += len(ids)
        elapsed = time.time() - t0
        rate = processed / elapsed if elapsed else 0
        eta = (total - processed) / rate / 60 if rate else 0
        sys.stdout.write(
            f"\r  processed {processed:,}/{total:,}  "
            f"({rate:,.0f}/s, ETA {eta:.1f} min)"
            + (f"  created={created:,} ignored={ignored:,} errors={errors:,}" if args.live else "")
        )
        sys.stdout.flush()

    print()
    elapsed = time.time() - t0
    print(f"Done in {elapsed/60:.1f} min. processed={processed:,}")
    if args.live:
        after = chunks.count()
        print(f"ArangoDB chunks (after): {after:,}  (+{after - before:,})")
        print(f"created={created:,} ignored(existing)={ignored:,} errors={errors:,}")
    else:
        print("Dry run complete — no writes. Re-run with --live to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
