#!/usr/bin/env python
"""
embed_missing_abstracts.py — backfill nomic embeddings for reproduction abstracts
that were never embedded, so the corpus reaches full coverage.

Finds abstracts in deb_abstracts_reproduction.abstracts whose doc_id has no row in
abstract_chunks, chunks the abstract text, embeds each chunk with nomic-embed-text
(Ollama, parallel workers), and inserts rows matching the existing schema:
    {doc_id, chunk_id, text, title, doi, publication_year, embedding}

Resumable: on restart it recomputes the embedded set and skips what's done.
Progress -> logs/embed_missing.log
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(REPO_ROOT, "app", "backend", ".env"))

OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DB = MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017"))["deb_abstracts_reproduction"]
WORKERS = int(os.environ.get("EMBED_WORKERS", "6"))
MAX_CHARS = 1500  # keep chunks under nomic-embed-text's 2048-token context
BATCH = 400  # abstracts per insert flush


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def chunk_text(text: str, mx: int = MAX_CHARS) -> list[str]:
    text = (text or "").strip()
    if len(text) <= mx:
        return [text] if text else []
    parts, cur = [], ""
    for w in text.split():
        if len(cur) + len(w) + 1 > mx:
            parts.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        parts.append(cur)
    return parts


def embed(text: str) -> list[float]:
    for attempt in range(6):
        try:
            r = requests.post(f"{OLLAMA}/api/embeddings",
                              json={"model": "nomic-embed-text", "prompt": text},
                              timeout=120)
            j = r.json()
            if "embedding" in j and j["embedding"]:
                return j["embedding"]
            raise RuntimeError(f"no embedding in response: {str(j)[:120]}")
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 * (attempt + 1))


def process_one(ab: dict) -> list[dict]:
    """Embed one abstract; on persistent failure skip it (return []) so the
    overall job keeps going — skipped abstracts are retried on a later run."""
    try:
        chunks = chunk_text(ab.get("abstract", ""))
        rows = []
        for i, ch in enumerate(chunks):
            rows.append({
                "doc_id": ab["doc_id"], "chunk_id": i, "text": ch,
                "title": ab.get("title"), "doi": ab.get("doi"),
                "publication_year": ab.get("publication_year"),
                "embedding": embed(ch),
            })
        return rows
    except Exception as exc:  # noqa: BLE001
        log(f"  SKIP {ab.get('doc_id')}: {exc}")
        return []


def main():
    t0 = time.time()
    log("building set of already-embedded doc_ids (aggregation) ...")
    embedded = set()
    for d in DB.abstract_chunks.aggregate([{"$group": {"_id": "$doc_id"}}], allowDiskUse=True):
        embedded.add(d["_id"])
    log(f"already embedded: {len(embedded):,} distinct abstracts")

    log("scanning abstracts for missing doc_ids ...")
    missing = []
    for a in DB.abstracts.find({}, {"doc_id": 1}):
        if a["doc_id"] not in embedded:
            missing.append(a["doc_id"])
    total = len(missing)
    log(f"to embed: {total:,} abstracts  (workers={WORKERS})")

    done = 0
    pending: list[dict] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for start in range(0, total, BATCH):
            ids = missing[start:start + BATCH]
            abs_docs = list(DB.abstracts.find(
                {"doc_id": {"$in": ids}},
                {"doc_id": 1, "abstract": 1, "title": 1, "doi": 1, "publication_year": 1}))
            results = ex.map(process_one, abs_docs)
            rows = [r for sub in results for r in sub]
            if rows:
                DB.abstract_chunks.insert_many(rows, ordered=False)
            done += len(abs_docs)
            if start // BATCH % 10 == 0 or done >= total:
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (total - done) / rate / 60 if rate else 0
                log(f"  {done:,}/{total:,} ({100*done/total:.1f}%)  {rate:.0f}/s  ETA {eta:.0f} min")
    log(f"DONE embedded {done:,} abstracts in {(time.time()-t0)/60:.0f} min")


if __name__ == "__main__":
    main()
