"""
Retroactively apply the domain-relevance gate to already-processed documents.

Why
---
The gate (``_classify_domain_relevance``, added 2026-08-25) screens documents on
title+abstract *before* the expensive stages run. But 10,760 abstract-corpus
documents were processed in 2026-06, two months earlier, so they never met it.
Sampling their titles turns up "Sardinia's nuraghi: Four millennia of becoming"
and "Static disassembly of obfuscated binaries"; only 3.8% mention any DEB or
bioenergetics term. Their 45,710 extracted facts are what fills the reproduction
graph.

This script judges those documents after the fact and *records* the verdict. It
deliberately does not delete facts or change ``processing_status`` — the verdict
lands in ``domain_relevant`` / ``domain_gate_reason`` so it can be reviewed,
queried, and reversed. Pruning is a separate, explicit decision.

Model
-----
The gate takes a ``model`` override precisely for bulk callers. Measured on
identical prompts, ``deepseek-r1:latest`` (the pipeline default, a reasoning
model) takes ~80s per call against ~1.1s for ``llama3.1:8b`` — 10 days versus
3 hours for this backfill. Validated on 12 documents: 6/6 DEB papers kept, clear
off-topic material dropped with sensible reasons. The gate also fails open, so a
model error keeps a document rather than dropping it.

Usage
-----
    python scripts/backfill_domain_gate.py --limit 200 --dry-run
    python scripts/backfill_domain_gate.py            # full run, resumable
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone

# The backend's Settings loads `.env` relative to the working directory, so run
# from there regardless of where this script was invoked.
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "app", "backend"))
sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)

from app.kb.pipeline import _classify_domain_relevance  # noqa: E402
from app.core.config import settings  # noqa: E402
from advandeb_kb.database.arango_client import ArangoDatabase  # noqa: E402

DEFAULT_MODEL = "llama3.1:8b"

# Documents already processed but never gated. `domain_relevant == null` makes
# the run resumable: re-running only picks up what has not been judged yet.
SELECT_AQL = """
FOR d IN documents
    FILTER d.processing_status == 'completed'
    FILTER d.domain_relevant == null
    SORT d._key
    LIMIT @limit
    RETURN {_key: d._key, title: d.title, abstract: d.abstract}
"""


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1_000_000)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = ArangoDatabase(
        settings.ARANGO_URL, settings.ARANGO_DB_NAME,
        settings.ARANGO_USERNAME, settings.ARANGO_PASSWORD,
    )
    db.connect()

    docs = db.aql(SELECT_AQL, bind_vars={"limit": args.limit})
    print(f"{len(docs)} ungated documents | model={args.model} "
          f"concurrency={args.concurrency} dry_run={args.dry_run}", flush=True)
    if not docs:
        return

    semaphore = asyncio.Semaphore(args.concurrency)
    now_iso = datetime.now(timezone.utc).isoformat()
    updates: list[dict] = []
    kept = dropped = 0
    started = time.time()

    async def judge(doc: dict) -> None:
        nonlocal kept, dropped
        async with semaphore:
            relevant, reason = await _classify_domain_relevance(
                doc.get("title") or "", doc.get("abstract"), model=args.model
            )
        if relevant:
            kept += 1
        else:
            dropped += 1
        updates.append({
            "_key": doc["_key"],
            "domain_relevant": relevant,
            "domain_gate_reason": reason,
            "domain_gate_model": args.model,
            "domain_gate_at": now_iso,
        })

    # Chunked so a long run reports progress and writes incrementally rather
    # than holding every result until the end.
    CHUNK = 400
    for start in range(0, len(docs), CHUNK):
        batch = docs[start:start + CHUNK]
        updates.clear()
        await asyncio.gather(*[judge(d) for d in batch])
        if not args.dry_run and updates:
            db.db.collection("documents").update_many(list(updates), silent=True)
        done = start + len(batch)
        rate = done / max(time.time() - started, 1e-9)
        print(f"  {done}/{len(docs)}  kept={kept} dropped={dropped}  "
              f"{rate:.1f} docs/s  eta {(len(docs)-done)/max(rate,1e-9)/60:.0f} min", flush=True)

    total = kept + dropped
    print(f"\nDONE {total} judged | kept {kept} ({100*kept/max(total,1):.1f}%) | "
          f"dropped {dropped} ({100*dropped/max(total,1):.1f}%) in "
          f"{(time.time()-started)/60:.1f} min", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
