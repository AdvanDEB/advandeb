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

Judging (the default) only *records* the verdict — ``domain_relevant`` /
``domain_gate_reason`` / ``domain_gate_version`` — so it can be reviewed,
queried, and reversed. ``--purge`` is the separate, explicit step that acts on
it (see below).

Re-gating
---------
The first pass (2026-08-27, gate v1 on ``llama3.1:8b``) recorded verdicts but
nothing acted on them, and v1 was lenient: human clinical medicine, R0
epidemiology and drug-resistance genetics went through as "relevant".
``--regate`` re-judges every document whose verdict predates
``DOMAIN_GATE_VERSION``, in both directions — a real paper the small model
dropped is kept again. The previous verdict is kept in ``domain_gate_prev``.

Scope
-----
``--domain`` (default ``reproduction``) limits every mode to one corpus. The
reproduction corpus was imported on a bare keyword and is mostly off-domain;
the PDF library is curated DEB literature, where title/abstract metadata is
often mismatched and the gate is the less reliable judge, so it is left alone
unless ``--domain any`` is passed.

Purge
-----
``--purge`` excludes every completed document judged off-domain: the document
record stays (``processing_status='excluded'`` + ``exclusion_reason``), while its
facts, chunks and graph edges are deleted — the same step as
``filter_reproduction_abstracts.py --propagate``, minus the vectors. All of it
is regenerable: to overturn a verdict, set the document back to pending and
re-run extraction.

The vectors are a separate step, ``--purge-vectors``, because ChromaDB is an
embedded store and the retrieval agent of ``advandeb-stack.service`` holds it
open with its index in memory: a second process writing to it is unsafe, and
the agent would go on serving deleted chunks anyway. Stop the stack, run
``--purge-vectors``, start it again. It deletes by ``document_id`` every vector
of an excluded document, so it can run any time after ``--purge``.

Model
-----
The gate takes a ``model`` override precisely for bulk callers. Measured on
identical prompts, ``deepseek-r1:latest`` (the pipeline default, a reasoning
model) takes ~80s per call against ~1.1s for ``llama3.1:8b``. With
``--openai-url`` the gate runs on an OpenAI-compatible server instead — the
vLLM Qwen3-32B on :8001 judges a dozen papers in about a second each, in
parallel, and sorts the v1 misses correctly. The key comes from
``GATE_OPENAI_API_KEY``. A failed call records nothing, so a re-run retries it.

Usage
-----
    python scripts/backfill_domain_gate.py --limit 200 --dry-run
    python scripts/backfill_domain_gate.py            # full run, resumable
    GATE_OPENAI_API_KEY=... python scripts/backfill_domain_gate.py --regate \\
        --openai-url http://127.0.0.1:8001 --model qwen3-32b --concurrency 32
    python scripts/backfill_domain_gate.py --purge --dry-run
    sudo systemctl stop advandeb-stack
    python scripts/backfill_domain_gate.py --purge-vectors
    sudo systemctl start advandeb-stack
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(_BACKEND)

from app.kb.pipeline import (  # noqa: E402
    DOMAIN_GATE_FAILED_REASON,
    DOMAIN_GATE_VERSION,
    _classify_domain_relevance,
)
from app.core.config import settings  # noqa: E402
from advandeb_kb.database.arango_client import ArangoDatabase  # noqa: E402

DEFAULT_MODEL = "llama3.1:8b"

# Documents already processed but never gated (or, with --regate, gated by an
# older prompt). Selecting on the verdict makes the run resumable: re-running
# only picks up what has not been judged yet.
SELECT_AQL = """
FOR d IN documents
    FILTER d.processing_status == 'completed'
    FILTER @domain == null OR d.general_domain == @domain
    FILTER d.domain_relevant == null
        OR (@regate AND d.domain_gate_version != @version)
    SORT d._key
    LIMIT @limit
    RETURN {_key: d._key, title: d.title, abstract: d.abstract,
            prev: d.domain_relevant == null ? null : {
                relevant: d.domain_relevant, reason: d.domain_gate_reason,
                model: d.domain_gate_model, at: d.domain_gate_at,
                version: d.domain_gate_version}}
"""

PURGE_SELECT_AQL = """
FOR d IN documents
    FILTER d.processing_status == 'completed' AND d.domain_relevant == false
    FILTER @domain == null OR d.general_domain == @domain
    SORT d._key
    LIMIT @limit
    RETURN [d._key, d.domain_gate_reason]
"""

EXCLUDED_EMBEDDED_AQL = """
FOR d IN documents
    FILTER d.processing_status == 'excluded' AND d.embedding_status == 'excluded'
    FILTER @domain == null OR d.general_domain == @domain
    SORT d._key
    LIMIT @limit
    RETURN d._key
"""


async def judge_all(db: ArangoDatabase, args: argparse.Namespace) -> None:
    api_key = os.environ.get("GATE_OPENAI_API_KEY") if args.openai_url else None
    if args.openai_url and not api_key:
        sys.exit("--openai-url needs GATE_OPENAI_API_KEY in the environment")

    docs = db.aql(SELECT_AQL, bind_vars={
        "limit": args.limit, "regate": args.regate, "version": DOMAIN_GATE_VERSION,
        "domain": args.domain})
    print(f"{len(docs)} documents to judge | gate v{DOMAIN_GATE_VERSION} model={args.model} "
          f"via={args.openai_url or 'ollama'} concurrency={args.concurrency} "
          f"dry_run={args.dry_run}", flush=True)
    if not docs:
        return

    semaphore = asyncio.Semaphore(args.concurrency)
    now_iso = datetime.now(timezone.utc).isoformat()
    updates: list[dict] = []
    kept = dropped = failed = flipped = 0
    started = time.time()

    async def judge(doc: dict) -> None:
        nonlocal kept, dropped, failed, flipped
        async with semaphore:
            relevant, reason = await _classify_domain_relevance(
                doc.get("title") or "", doc.get("abstract"), model=args.model,
                base_url=args.openai_url, openai_api_key=api_key,
            )
        if reason == DOMAIN_GATE_FAILED_REASON:
            # Fail-open is right for live ingestion, but recording it here
            # would mark the document judged and hide it from every re-run.
            failed += 1
            return
        if relevant:
            kept += 1
        else:
            dropped += 1
        prev = doc.get("prev")
        if prev is not None and prev.get("relevant") != relevant:
            flipped += 1
        update = {
            "_key": doc["_key"],
            "domain_relevant": relevant,
            "domain_gate_reason": reason,
            "domain_gate_model": args.model,
            "domain_gate_version": DOMAIN_GATE_VERSION,
            "domain_gate_at": now_iso,
        }
        if prev is not None:
            update["domain_gate_prev"] = prev
        updates.append(update)

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
        print(f"  {done}/{len(docs)}  kept={kept} dropped={dropped} failed={failed} "
              f"flipped={flipped}  {rate:.1f} docs/s  "
              f"eta {(len(docs)-done)/max(rate,1e-9)/60:.0f} min", flush=True)

    total = kept + dropped
    print(f"\nDONE {total} judged | kept {kept} ({100*kept/max(total,1):.1f}%) | "
          f"dropped {dropped} ({100*dropped/max(total,1):.1f}%) | "
          f"verdict changed {flipped} | failed (not recorded) {failed} in "
          f"{(time.time()-started)/60:.1f} min", flush=True)


def purge(db: ArangoDatabase, args: argparse.Namespace) -> None:
    from filter_reproduction_abstracts import _purge_batch

    rows = db.aql(PURGE_SELECT_AQL, bind_vars={"limit": args.limit, "domain": args.domain})
    reasons = {k: (r or "off-topic per domain gate") for k, r in rows}
    keys = list(reasons)
    print(f"{len(keys)} off-domain documents to exclude | dry_run={args.dry_run}", flush=True)
    if not keys:
        return

    totals: dict[str, int] = {}
    started = time.time()
    for i in range(0, len(keys), args.purge_batch):
        n = _purge_batch(db, None, keys[i:i + args.purge_batch], reasons, args.dry_run)
        for k, v in n.items():
            totals[k] = totals.get(k, 0) + v
        print(f"  {min(i + args.purge_batch, len(keys))}/{len(keys)}  {totals}  "
              f"({time.time() - started:.0f}s)", flush=True)

    verb = "would remove" if args.dry_run else "removed"
    print(f"\nDONE {verb} for {totals.get('documents', 0)} documents: {totals}", flush=True)
    if totals.get("embedded_docs"):
        print(f"{totals['embedded_docs']} of them have vectors: stop advandeb-stack and "
              f"run --purge-vectors", flush=True)


def purge_vectors(db: ArangoDatabase, args: argparse.Namespace) -> None:
    from advandeb_kb.config.settings import settings as kb_settings
    from advandeb_kb.services.chromadb_service import ChromaDBService

    # Run from a worktree, the default persist dir resolves inside it and
    # Chroma would quietly create an empty store there.
    if not os.path.isdir(kb_settings.CHROMA_PERSIST_DIR):
        sys.exit(f"No ChromaDB at {kb_settings.CHROMA_PERSIST_DIR}; set CHROMA_PERSIST_DIR")

    keys = db.aql(EXCLUDED_EMBEDDED_AQL, bind_vars={"limit": args.limit, "domain": args.domain})
    chroma = ChromaDBService()
    before = chroma.count()
    print(f"{len(keys)} excluded documents with vectors | ChromaDB {chroma.persist_dir} "
          f"holds {before} | dry_run={args.dry_run}", flush=True)
    if not keys or args.dry_run:
        return
    started = time.time()
    for i in range(0, len(keys), args.purge_batch):
        chroma.collection.delete(where={"document_id": {"$in": keys[i:i + args.purge_batch]}})
        print(f"  {min(i + args.purge_batch, len(keys))}/{len(keys)}  "
              f"({time.time() - started:.0f}s)", flush=True)
    after = chroma.count()
    print(f"\nDONE removed {before - after} vectors; ChromaDB now holds {after}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1_000_000)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true",
                        help="Judge: classify but don't write; purge: count only")
    parser.add_argument("--regate", action="store_true",
                        help=f"Also re-judge verdicts older than gate v{DOMAIN_GATE_VERSION}")
    parser.add_argument("--openai-url", default=None,
                        help="OpenAI-compatible server (e.g. vLLM) instead of Ollama; "
                             "key from GATE_OPENAI_API_KEY")
    parser.add_argument("--purge", action="store_true",
                        help="Exclude off-domain documents and delete their facts, chunks, edges")
    parser.add_argument("--purge-vectors", action="store_true",
                        help="Delete ChromaDB vectors of excluded documents (stop advandeb-stack first)")
    parser.add_argument("--purge-batch", type=int, default=200)
    parser.add_argument("--domain", default="reproduction",
                        help="general_domain to work on, or 'any'")
    args = parser.parse_args()
    if args.domain == "any":
        args.domain = None

    db = ArangoDatabase(
        settings.ARANGO_URL, settings.ARANGO_DB_NAME,
        settings.ARANGO_USERNAME, settings.ARANGO_PASSWORD,
    )
    db.connect()

    if args.purge:
        purge(db, args)
    elif args.purge_vectors:
        purge_vectors(db, args)
    else:
        asyncio.run(judge_all(db, args))


if __name__ == "__main__":
    main()
