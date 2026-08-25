#!/usr/bin/env python
"""
rebuild_repro_index.py — build a fresh reproduction vector index from the CURRENT
full abstract_chunks in MongoDB (now ~100% embedded), bypassing the stale Jan-21
20GB cache and the equally-stale embeddings_export shards.

Writes a FastVectorIndex-compatible cache: {embeddings: np.ndarray (N,768) float32
normalised, metadata: list[dict(doc_id,title,doi,publication_year,text)]} to
    ~/dev/advandeb_auxiliary/stylized_DEB/data/repro_full_index_cache.pkl
"""
from __future__ import annotations

import os
import pickle
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from pymongo import MongoClient

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / "app" / "backend" / ".env")
OUT = Path.home() / "dev" / "advandeb_auxiliary" / "stylized_DEB" / "data" / "repro_full_index_cache.pkl"
TEXT_CHARS = 800  # store enough for snippet display; keeps metadata RAM bounded

db = MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017"))["deb_abstracts_reproduction"]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    t0 = time.time()
    n = db.abstract_chunks.estimated_document_count()
    log(f"allocating index for ~{n:,} chunks (will trim to actual)")
    emb = np.empty((n + 1000, 768), dtype=np.float32)
    meta: list[dict] = []
    i = 0
    cur = db.abstract_chunks.find(
        {}, {"embedding": 1, "doc_id": 1, "text": 1, "title": 1, "doi": 1, "publication_year": 1},
        batch_size=2000, no_cursor_timeout=True)
    try:
        for d in cur:
            v = d.get("embedding")
            if not v or len(v) != 768:
                continue
            if i >= emb.shape[0]:
                emb = np.vstack([emb, np.empty((100000, 768), dtype=np.float32)])
            emb[i] = v
            meta.append({"doc_id": d.get("doc_id"),
                         "title": d.get("title") or "(untitled)",
                         "doi": d.get("doi") or "",
                         "publication_year": d.get("publication_year") or "",
                         "text": (d.get("text") or "")[:TEXT_CHARS]})
            i += 1
            if i % 250000 == 0:
                el = time.time() - t0
                log(f"  loaded {i:,} ({i/el:.0f}/s, {el/60:.1f} min)")
    finally:
        cur.close()

    emb = emb[:i]
    log(f"loaded {i:,} vectors; normalising …")
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    emb /= norms
    log(f"saving cache -> {OUT}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "wb") as f:
        pickle.dump({"embeddings": emb, "metadata": meta}, f, protocol=pickle.HIGHEST_PROTOCOL)
    log(f"DONE {i:,} vectors in {(time.time()-t0)/60:.1f} min -> {OUT}")


if __name__ == "__main__":
    main()
