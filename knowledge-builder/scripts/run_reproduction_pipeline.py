"""
Structured knowledge extraction over imported *reproduction* abstracts → ArangoDB.

For each abstract document (``general_domain=='reproduction'`` and
``processing_status=='pending'``) a single small-model LLM call extracts a
structured record from the abstract text:

  - **conclusion**           — the main conclusion/finding of the abstract (1 statement)
  - **background_knowledge**  — facts the abstract assumes/implies from general
                                knowledge or prior work (NOT the paper's own new result)
  - **citations**             — other works/papers the abstract refers to

Each extracted item is stored as a ``facts`` document with a ``fact_type`` field
(``conclusion`` | ``background_knowledge`` | ``citation``), ``document_id`` = the
abstract's ``_key``, ``general_domain='reproduction'``. The abstract itself is the
document node (graph node_type ``abstract``); the graph serializer renders each
``fact_type`` as its own node type. No stylized-fact matching here.

Built for small models at modest concurrency. Run in the background, e.g.:

    cd /home/adeb/dev/advandeb && set -a && . app/backend/.env && set +a
    nohup env OLLAMA_MODEL=gemma2:2b conda run -n advandeb python \\
        knowledge-builder/scripts/run_reproduction_pipeline.py --concurrency 4 \\
        > /tmp/repro_facts_full.log 2>&1 &

Resumable: a doc's status flips to ``completed`` only after its facts are written,
and selection always targets ``pending`` — so a crash/restart simply continues.
Re-running a half-done doc creates no duplicates (``content_fingerprint`` dedup).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.config.settings import settings  # noqa: E402

try:
    from bson import ObjectId  # 24-char hex keys, matching existing facts

    def _new_fact_key() -> str:
        return str(ObjectId())
except Exception:  # noqa: BLE001
    import uuid

    def _new_fact_key() -> str:
        return uuid.uuid4().hex[:24]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("repro_pipeline")

GENERAL_DOMAIN = "reproduction"
SEM: asyncio.Semaphore
# Overridable Ollama endpoint (set per-worker so each worker hits a different
# GPU-pinned Ollama instance). Defaults to the configured base URL.
_OLLAMA_URL = settings.OLLAMA_BASE_URL

_SYSTEM = (
    "You analyze a scientific paper ABSTRACT and extract a structured JSON object. "
    "Return ONLY a JSON object with EXACTLY these keys:\n"
    '  "conclusion": one concise sentence stating the main conclusion/finding of the abstract.\n'
    '  "background_knowledge": array of short factual statements the abstract assumes or implies '
    "from general scientific knowledge or prior work (NOT the paper's own new findings); [] if none.\n"
    '  "citations": array of short strings naming other works/papers/datasets the abstract refers '
    "to (e.g. 'previous studies on X', author-year if present); [] if none.\n"
    "Keep every string under 240 characters. No markdown, no commentary."
)


# ---------------------------------------------------------------------------
# Fingerprint — MUST match app/backend/app/kb/pipeline.py::_fingerprint
# ---------------------------------------------------------------------------

def _fingerprint(text: str) -> str:
    norm = re.sub(r"[^a-z0-9 ]", "", text.lower())
    return " ".join(norm.split())[:120]


async def _aql_update(a, query: str, binds: Dict[str, Any], attempts: int = 6) -> bool:
    """Run an UPDATE AQL with retry/backoff. Lock-wait timeouts (HTTP 409) happen
    when the embedding job updates the same documents concurrently; retry rather
    than crash. Returns True on success; on persistent failure the doc is left for
    a later pass (fact writes are dedupe-safe)."""
    for i in range(attempts):
        try:
            a.aql(query, binds)
            return True
        except Exception as exc:  # noqa: BLE001
            if i == attempts - 1:
                logger.warning("status update failed after %d tries: %s", attempts, str(exc)[:120])
                return False
            await asyncio.sleep(0.4 * (i + 1))
    return False


def _norm_list(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


# ---------------------------------------------------------------------------
# LLM extraction (single structured call per abstract)
# ---------------------------------------------------------------------------

async def _extract_structured(text: str, timeout: float) -> Dict[str, Any]:
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"ABSTRACT:\n\n{text[:8000]}"},
        ],
        "stream": False,
        "format": "json",  # force valid JSON output (Ollama)
        "options": {"temperature": 0.1},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{_OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
        content = resp.json()["message"]["content"].strip()
    try:
        clean = content
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(clean)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _items_from(data: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Flatten the structured record into (fact_type, text) pairs."""
    items: List[Tuple[str, str]] = []
    concl = data.get("conclusion")
    if isinstance(concl, str) and concl.strip():
        items.append(("conclusion", concl.strip()))
    elif isinstance(concl, list):
        for c in _norm_list(concl):
            items.append(("conclusion", c))
    for b in _norm_list(data.get("background_knowledge")):
        items.append(("background_knowledge", b))
    for c in _norm_list(data.get("citations")):
        items.append(("citation", c))
    return items


# ---------------------------------------------------------------------------
# Per-document processing (Arango writes are synchronous)
# ---------------------------------------------------------------------------

async def process_one(doc: Dict[str, Any], a, dry_run: bool, timeout: float) -> Tuple[str, int]:
    """Returns (status, items_added)."""
    key = doc["_key"]
    content = (doc.get("content") or doc.get("abstract") or "").strip()

    if len(content) < 100:
        if not dry_run:
            await _aql_update(a, "FOR d IN documents FILTER d._key==@k UPDATE d "
                              "WITH {processing_status:'skipped', updated_at:@t} IN documents",
                              {"k": key, "t": datetime.now(timezone.utc).isoformat()})
        return "skipped", 0

    async with SEM:
        try:
            data = await _extract_structured(content, timeout)
        except Exception as exc:  # noqa: BLE001 — leave 'pending' for retry
            logger.warning("extract failed for %s: %s", key, exc)
            return "error", 0

    items = _items_from(data)

    if dry_run:
        by_type = {t: sum(1 for tt, _ in items if tt == t)
                   for t in ("conclusion", "background_knowledge", "citation")}
        logger.info("DRY-RUN %s -> %s", key, by_type)
        return "dry_run", len(items)

    now = datetime.now(timezone.utc).isoformat()
    existing = set(a.aql(
        "FOR f IN facts FILTER f.document_id==@d RETURN f.content_fingerprint", {"d": key}))

    new_facts: List[Dict[str, Any]] = []
    seen = set()
    for ftype, txt in items:
        fp = _fingerprint(txt)
        if not fp or fp in existing or fp in seen:
            continue
        seen.add(fp)
        new_facts.append({
            "_key": _new_fact_key(), "content": txt, "document_id": key,
            "content_fingerprint": fp, "fact_type": ftype,
            "page_number": None, "entities": [], "tags": ["abstract", ftype],
            "general_domain": GENERAL_DOMAIN, "confidence": 0.7, "status": "pending",
            "additional_sources": [], "created_at": now, "updated_at": now,
        })

    if new_facts:
        a.db.collection("facts").import_bulk(new_facts, on_duplicate="ignore", halt_on_error=False)

    await _aql_update(a, "FOR d IN documents FILTER d._key==@k UPDATE d "
                      "WITH {processing_status:'completed', num_facts:@n, updated_at:@t} IN documents",
                      {"k": key, "n": len(new_facts), "t": now})
    return "completed", len(new_facts)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

async def run(limit: int, batch_size: int, concurrency: int, dry_run: bool, timeout: float,
              shard: int = 0, num_shards: int = 1) -> None:
    global SEM
    SEM = asyncio.Semaphore(concurrency)

    # Disjoint sharding by key so N workers (one per GPU) never touch the same doc.
    shard_clause = ""
    shard_binds: Dict[str, Any] = {}
    if num_shards > 1:
        shard_clause = "AND (((TO_NUMBER(SUBSTRING(d._key, 1)) OR 0) % @m) == @i)"
        shard_binds = {"m": num_shards, "i": shard}

    from advandeb_kb.database.arango_client import ArangoDatabase
    a = ArangoDatabase()
    a.connect()

    pending = a.aql(
        f"RETURN LENGTH(FOR d IN documents "
        f"FILTER d.general_domain==@g AND d.processing_status=='pending' {shard_clause} RETURN 1)",
        {"g": GENERAL_DOMAIN, **shard_binds})[0]
    logger.info("model=%s url=%s shard=%d/%d concurrency=%d | pending(this shard)=%d (limit=%s)",
                settings.OLLAMA_MODEL, _OLLAMA_URL, shard, num_shards, concurrency,
                pending, limit or "all")
    if pending == 0:
        logger.info("Nothing to process.")
        return

    counts = {"completed": 0, "skipped": 0, "error": 0, "dry_run": 0}
    total_items = processed = 0
    start = time.time()
    unlimited = (limit == 0)
    remaining = limit if limit else pending

    while unlimited or remaining > 0:
        take = batch_size if unlimited else min(batch_size, remaining)
        docs = a.aql(
            f"FOR d IN documents FILTER d.general_domain==@g AND d.processing_status=='pending' "
            f"{shard_clause} LIMIT @n RETURN d", {"g": GENERAL_DOMAIN, "n": take, **shard_binds})
        if not docs:
            break
        results = await asyncio.gather(*[process_one(d, a, dry_run, timeout) for d in docs])
        for status, n in results:
            counts[status] = counts.get(status, 0) + 1
            total_items += n
            processed += 1
        el = time.time() - start
        rate = processed / el if el else 0
        logger.info("progress: %d processed (%.2f docs/s) completed=%d skipped=%d error=%d items=%d",
                    processed, rate, counts["completed"], counts["skipped"], counts["error"], total_items)
        if not unlimited:
            remaining -= len(docs)
        if dry_run:
            break

    logger.info("DONE — processed=%d completed=%d skipped=%d error=%d items=%d in %.1fs",
                processed, counts["completed"], counts["skipped"], counts["error"],
                total_items, time.time() - start)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, default=0, help="Max docs this run (0=all pending)")
    p.add_argument("--batch-size", type=int, default=40, help="Docs per round")
    p.add_argument("--concurrency", type=int, default=4, help="Parallel LLM calls")
    p.add_argument("--timeout", type=float, default=180.0, help="Ollama timeout seconds")
    p.add_argument("--dry-run", action="store_true", help="Count + extract one batch, write nothing")
    p.add_argument("--ollama-url", default=None, help="Override Ollama endpoint (per-GPU worker)")
    p.add_argument("--shard", type=int, default=0, help="This worker's shard index [0, num-shards)")
    p.add_argument("--num-shards", type=int, default=1, help="Total workers sharding the corpus")
    args = p.parse_args()
    global _OLLAMA_URL
    if args.ollama_url:
        _OLLAMA_URL = args.ollama_url.rstrip("/")
    asyncio.run(run(args.limit, args.batch_size, args.concurrency, args.dry_run, args.timeout,
                    shard=args.shard, num_shards=args.num_shards))


if __name__ == "__main__":
    main()
