#!/usr/bin/env python3
"""
Create the ArangoSearch view that gives hybrid retrieval its BM25 keyword arm.

HybridRetrievalService searches ``chunks.text`` through this view (settings
RETRIEVAL_CHUNKS_VIEW / RETRIEVAL_TEXT_ANALYZER). Until it exists the
RetrievalAgent falls back to MongoDB $text over the frozen legacy ``chunks``
collection (~264k chunks), while the vector arm searches all of ChromaDB.

What it creates (idempotent — re-running changes nothing that is already right):
  * analyzer ``advandeb_text_en``: English text analyzer, lower case, accents
    folded, stemmed, Lucene's English stop words, features frequency + norm
    (what BM25 needs; no positions, so no PHRASE, and a smaller index);
  * view ``chunks_text_search``: links ``chunks`` on ``text`` (that analyzer)
    and ``general_domain`` (identity, for the domain filter). The link is built
    with inBackground=true, so the collection stays writable while it builds.

Dry run by default: prints the current state and what would be done. Any
database whose name does not mark it as scratch is treated as production and
additionally needs --production and a successful backup of that database from
the last 26 hours (advandeb_kb.backup_guard.require_recent_backup).

Measured on a scratch copy of production ``chunks`` (3,077,659 docs, 2.3 GB of
JSON; Arango 3.12.8): see --wait output; numbers are recorded in the retrieval
quality report.

Usage:
    python setup_chunks_search_view.py --db advandeb_kb_retrieval_scratch            # dry run
    python setup_chunks_search_view.py --db advandeb_kb_retrieval_scratch --apply --wait
    python setup_chunks_search_view.py --db advandeb_kb --production --apply --wait  # production
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.config.settings import settings  # noqa: E402
from advandeb_kb.database import text_search as ts  # noqa: E402

COLLECTION = "chunks"
SCRATCH_MARKERS = ("scratch", "_test", "test_", "sandbox", "tmp")


def link_definition(analyzer: str) -> dict:
    return {
        "includeAllFields": False,
        "storeValues": "none",
        "trackListPositions": False,
        "inBackground": True,
        "fields": {
            "text": {"analyzers": [analyzer]},
            "general_domain": {"analyzers": ["identity"]},
        },
    }


def is_scratch(db_name: str) -> bool:
    name = db_name.strip().lower()
    return name != "advandeb_kb" and any(m in name for m in SCRATCH_MARKERS)


def connect(db_name: str):
    from arango import ArangoClient

    client = ArangoClient(hosts=settings.ARANGO_URL, request_timeout=6 * 3600)
    return client.db(db_name, username=settings.ARANGO_USERNAME, password=settings.ARANGO_PASSWORD)


def rest_get(path: str) -> dict:
    req = urllib.request.Request(settings.ARANGO_URL.rstrip("/") + path)
    token = base64.b64encode(f"{settings.ARANGO_USERNAME}:{settings.ARANGO_PASSWORD}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def arangod_rss_gb() -> Optional[float]:
    """Resident memory of the local arangod process, if it can be read."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if Path(f"/proc/{pid}/comm").read_text().strip() != "arangod":
                continue
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024 / 1024
        except OSError:
            continue
    return None


def link_stats(db_name: str) -> Optional[dict]:
    # A link lists its view by internal id, not by name; chunks has one link.
    data = rest_get(f"/_db/{db_name}/_api/index?collection={COLLECTION}&withStats=true&withHidden=true")
    for idx in data.get("indexes", []):
        if idx.get("type") == "arangosearch":
            return idx.get("figures") or {}
    return None


def view_state(db, view: str, analyzer: str) -> str:
    if not any(v["name"] == view for v in db.views()):
        return "missing"
    props = db.view(view)
    link = (props.get("links") or {}).get(COLLECTION)
    return ts.link_state(link, link_definition(analyzer)["fields"])


def count_indexed(db, view: str) -> int:
    cursor = db.aql.execute(
        "FOR d IN @@view SEARCH true OPTIONS {waitForSync: false} COLLECT WITH COUNT INTO n RETURN n",
        bind_vars={"@view": view},
    )
    return next(iter(cursor), 0)


def wait_for_build(db, db_name: str, view: str, total: int, started: float) -> None:
    last = -1
    while True:
        n = count_indexed(db, view)
        rss = arangod_rss_gb()
        if n != last:
            print(
                f"  {time.time() - started:7.0f}s indexed {n:,}/{total:,}"
                + (f"  arangod RSS {rss:.1f} GB" if rss is not None else ""),
                flush=True,
            )
            last = n
        if n >= total:
            break
        time.sleep(15)
    stats = link_stats(db_name) or {}
    print(f"Build complete in {time.time() - started:.0f}s; link figures: {json.dumps(stats)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=settings.ARANGO_DB_NAME, help="target database (default: settings.ARANGO_DB_NAME)")
    ap.add_argument("--view", default=settings.RETRIEVAL_CHUNKS_VIEW)
    ap.add_argument("--analyzer", default=settings.RETRIEVAL_TEXT_ANALYZER)
    ap.add_argument("--apply", action="store_true", help="create what is missing (default: dry run)")
    ap.add_argument("--wait", action="store_true", help="after --apply, poll until every chunk is indexed")
    ap.add_argument("--production", action="store_true",
                    help="required for a database not marked as scratch")
    ap.add_argument("--backup-max-age-hours", type=float, default=26.0)
    args = ap.parse_args()

    scratch = is_scratch(args.db)
    print(f"Database: {args.db} ({'scratch' if scratch else 'PRODUCTION'})")

    db = connect(args.db)
    total = db.collection(COLLECTION).count()
    a_state = ts.analyzer_state(db, args.analyzer)
    v_state = view_state(db, args.view, args.analyzer)
    print(f"{COLLECTION}: {total:,} documents")
    print(f"analyzer {args.analyzer}: {a_state}")
    print(f"view {args.view}: {v_state}")

    if a_state.startswith("differs"):
        print("The analyzer exists with other settings. Analyzers cannot be changed in place: "
              "drop the view and analyzer by hand (or pick another --analyzer name) and re-run.")
        return 2

    actions = []
    if a_state == "missing":
        actions.append("create analyzer")
    if v_state == "missing":
        actions.append("create view (builds the link in the background)")
    elif v_state != "ok":
        actions.append("update view link (re-indexes the collection in the background)")

    if not actions:
        print("Nothing to do.")
        if args.wait:
            wait_for_build(db, args.db, args.view, total, time.time())
        return 0

    print("Planned: " + "; ".join(actions))
    if not args.apply:
        print("Dry run — re-run with --apply to make these changes.")
        return 0

    if not scratch:
        if not args.production:
            print("Refusing: this is a production database. Pass --production to confirm.")
            return 2
        try:
            from advandeb_kb.backup_guard import require_recent_backup
        except ImportError:
            print("Refusing: advandeb_kb.backup_guard is not available, so the backup "
                  "precondition cannot be checked.")
            return 2
        manifest = require_recent_backup(f"arango:{args.db}", max_age_hours=args.backup_max_age_hours)
        print(f"Backup check passed: {manifest['_path']}")

    started = time.time()
    rss_before = arangod_rss_gb()
    if rss_before is not None:
        print(f"arangod RSS before: {rss_before:.1f} GB")

    if a_state == "missing":
        ts.create_analyzer(db, args.analyzer)
        print(f"Created analyzer {args.analyzer}")

    links = {COLLECTION: link_definition(args.analyzer)}
    if v_state == "missing":
        properties = {"links": links, "optimizeTopK": ["BM25(@doc) DESC"]}
        try:
            db.create_arangosearch_view(args.view, properties=properties)
        except Exception as exc:
            # optimizeTopK (WAND) is an Enterprise feature; retry without it.
            if "optimizeTopK" not in str(exc):
                raise
            print(f"optimizeTopK not accepted ({exc}); creating without it")
            db.create_arangosearch_view(args.view, properties={"links": links})
        print(f"Created view {args.view}")
    else:
        db.update_arangosearch_view(args.view, properties={"links": links})
        print(f"Updated view {args.view}")

    if args.wait:
        wait_for_build(db, args.db, args.view, total, started)
        rss_after = arangod_rss_gb()
        if rss_before is not None and rss_after is not None:
            print(f"arangod RSS after: {rss_after:.1f} GB (delta {rss_after - rss_before:+.1f} GB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
