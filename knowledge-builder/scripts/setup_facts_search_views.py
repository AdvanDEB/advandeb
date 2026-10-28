#!/usr/bin/env python3
"""
Create the ArangoSearch views that give facts and stylized facts BM25 search.

KnowledgeService.search_facts / search_stylized_facts search ``facts.content``
and ``stylized_facts.statement`` through these views (settings
FACTS_SEARCH_VIEW / STYLIZED_FACTS_SEARCH_VIEW). Until they exist, both fall
back to an unranked LIKE scan of the whole collection that only finds the query
as one exact substring. Definitions live in advandeb_kb.database.text_search.

What it creates (idempotent — re-running changes nothing that is already right):
  * analyzer settings.RETRIEVAL_TEXT_ANALYZER (``advandeb_text_en``) unless it
    exists — the chunks view uses the same one; an existing analyzer with
    other settings is refused, not changed;
  * view ``facts_text_search``: ``facts`` on ``content`` (that analyzer) and
    ``general_domain`` (identity, for the domain filter);
  * view ``stylized_facts_text_search``: ``stylized_facts`` on ``statement``
    and ``category`` (identity).
  Links are built with inBackground=true: the collections stay writable.

With --drop-stale-fulltext it also drops the FULLTEXT indexes on
``facts.text`` and ``stylized_facts.description``. Those attributes do not
exist, so the indexes are empty and nothing uses them; setup_schema no longer
creates them.

Dry run by default: prints the current state and what would be done. Any
database whose name does not mark it as scratch is treated as production and
additionally needs --production and a successful backup of that database from
the last 26 hours (advandeb_kb.backup_guard.require_recent_backup).

Usage:
    python setup_facts_search_views.py --db advandeb_kb_factsearch_scratch          # dry run
    python setup_facts_search_views.py --db advandeb_kb_factsearch_scratch --apply --wait
    python setup_facts_search_views.py --db advandeb_kb --production --apply --wait  # production
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.config.settings import settings  # noqa: E402
from advandeb_kb.database import text_search as ts  # noqa: E402

# FULLTEXT indexes setup_schema used to create on attributes no document has.
STALE_FULLTEXT = [("facts", "text"), ("stylized_facts", "description")]

SCRATCH_MARKERS = ("scratch", "_test", "test_", "sandbox", "tmp")


def is_scratch(db_name: str) -> bool:
    name = db_name.strip().lower()
    return name != "advandeb_kb" and any(m in name for m in SCRATCH_MARKERS)


def connect(db_name: str):
    from arango import ArangoClient

    client = ArangoClient(hosts=settings.ARANGO_URL, request_timeout=3600)
    return client.db(db_name, username=settings.ARANGO_USERNAME, password=settings.ARANGO_PASSWORD)


def stale_fulltext_indexes(db) -> list[tuple[str, dict]]:
    found = []
    for collection, field in STALE_FULLTEXT:
        if not db.has_collection(collection):
            continue
        for idx in db.collection(collection).indexes():
            if idx.get("type") == "fulltext" and idx.get("fields") == [field]:
                found.append((collection, idx))
    return found


def wait_for_build(db, started: float) -> None:
    pending = list(ts.VIEWS)
    while pending:
        for view in list(pending):
            n = ts.count_indexed(db, view)
            total = db.collection(view.collection).count()
            print(f"  {time.time() - started:6.1f}s {view.name}: indexed {n:,}/{total:,}", flush=True)
            if n >= total:
                pending.remove(view)
        if pending:
            time.sleep(2)
    print(f"Build complete in {time.time() - started:.1f}s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=settings.ARANGO_DB_NAME, help="target database (default: settings.ARANGO_DB_NAME)")
    ap.add_argument("--apply", action="store_true", help="make the planned changes (default: dry run)")
    ap.add_argument("--wait", action="store_true", help="poll until every document is indexed")
    ap.add_argument("--drop-stale-fulltext", action="store_true",
                    help="also drop the FULLTEXT indexes on facts.text and stylized_facts.description")
    ap.add_argument("--production", action="store_true",
                    help="required for a database not marked as scratch")
    ap.add_argument("--backup-max-age-hours", type=float, default=26.0)
    args = ap.parse_args()

    scratch = is_scratch(args.db)
    print(f"Database: {args.db} ({'scratch' if scratch else 'PRODUCTION'})")

    db = connect(args.db)
    totals = {}
    for view in ts.VIEWS:
        if not db.has_collection(view.collection):
            print(f"Collection {view.collection!r} does not exist in {args.db}.")
            return 2
        totals[view.collection] = db.collection(view.collection).count()

    a_state = ts.analyzer_state(db)
    print(f"analyzer {ts.TEXT_ANALYZER}: {a_state}")
    if a_state.startswith("differs"):
        print("The analyzer exists with other settings and analyzers cannot be changed in "
              "place. Resolve that by hand (other views may use it) and re-run.")
        return 2

    v_states = {}
    for view in ts.VIEWS:
        v_states[view] = ts.view_state(db, view)
        print(f"view {view.name} ({view.collection}: {totals[view.collection]:,} docs): {v_states[view]}")

    stale = stale_fulltext_indexes(db)
    for collection, idx in stale:
        print(f"stale FULLTEXT index {collection}.{idx['fields'][0]} ({idx['id']})")

    actions = []
    if a_state == "missing":
        actions.append(f"create analyzer {ts.TEXT_ANALYZER}")
    for view, state in v_states.items():
        if state == "missing":
            actions.append(f"create view {view.name} (builds in the background)")
        elif state != "ok":
            actions.append(f"update view {view.name} link (re-indexes {view.collection})")
    if stale and args.drop_stale_fulltext:
        actions.append(f"drop {len(stale)} stale FULLTEXT index(es)")
    elif stale:
        print("(pass --drop-stale-fulltext to drop them)")

    if not actions:
        print("Nothing to do.")
        if args.wait:
            wait_for_build(db, time.time())
        return 0

    print("Planned: " + "; ".join(actions))
    if not args.apply:
        print("Dry run — re-run with --apply to make these changes.")
        return 0

    if not scratch:
        if not args.production:
            print("Refusing: this is a production database. Pass --production to confirm.")
            return 2
        from advandeb_kb.backup_guard import NoRecentBackupError, require_recent_backup

        try:
            manifest = require_recent_backup(f"arango:{args.db}", max_age_hours=args.backup_max_age_hours)
        except NoRecentBackupError as exc:
            print(f"Refusing: {exc}")
            return 2
        print(f"Backup check passed: {manifest['_path']}")

    started = time.time()
    if a_state == "missing":
        ts.create_analyzer(db)
        print(f"Created analyzer {ts.TEXT_ANALYZER}")
    for view, state in v_states.items():
        if state == "ok":
            continue
        ts.create_or_update_view(db, view, state)
        print(f"{'Created' if state == 'missing' else 'Updated'} view {view.name}")
    if stale and args.drop_stale_fulltext:
        for collection, idx in stale:
            db.collection(collection).delete_index(idx["id"].split("/")[-1])
            print(f"Dropped FULLTEXT index {collection}.{idx['fields'][0]}")

    if args.wait:
        wait_for_build(db, started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
