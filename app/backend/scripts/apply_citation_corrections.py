#!/usr/bin/env python3
"""Apply the citation report's high-confidence corrections to ArangoDB.

Experts see each evidence passage with a citation joined, at serve time, from
the curated `documents` records (app/services/passage_citation_service.py).
The 2026-10-28 citation report (scripts/passage_citations_report.py) found
those records wrong or thin in places — 44 DEB papers carried a DOI that
resolves to a different work, and most reproduction records lacked authors and
journal — and wrote its high-confidence fixes to
`docs/elicitation/citations/citation_corrections.json`. ArangoDB is canonical for document
metadata (docs/STORAGE-CONTRACT.md), so the fix belongs there, not in a file
the app reads beside it.

**This writes to the production knowledge store.** It is a DRY RUN unless
`--apply` is given, and it never overwrites a value that changed since the
report was made: each correction carries the `old` value it was computed
against, and a field whose stored value differs is skipped and listed. Before
applying, the current value of every field it will touch is saved to a backup
file, so the change can be reverted exactly (`--revert BACKUP`).

The frozen evidence sets are not touched: a citation is a label on a passage,
never part of it.

Usage (from app/backend/, conda env advandeb):

    python scripts/apply_citation_corrections.py                    # dry run, all fields
    python scripts/apply_citation_corrections.py --fields doi       # dry run, DOIs only
    python scripts/apply_citation_corrections.py --fields doi --apply
    python scripts/apply_citation_corrections.py --revert scripts/out/citation_corrections.backup.<ts>.json --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# The reviewed, committed copy; plans and backups go to the git-ignored
# working directory beside the report's own outputs.
DEFAULT_INPUT = (BACKEND.parents[1] / "docs" / "elicitation" / "citations"
                 / "citation_corrections.json")
OUT_DIR = BACKEND / "scripts" / "out"
FIELDS = ("doi", "title", "authors", "year", "journal")
SOURCE = "citation-report-2026-10-28"


def _same(stored: Any, old: Any) -> bool:
    """Whether the stored value is still the one the report saw. Both sides
    are raw stored values, so a plain comparison suffices; a list and its
    stringified form are treated as different on purpose."""
    return stored == old


def plan(corrections: Dict[str, Any], fields: Tuple[str, ...], fetch
         ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The updates to make, and the corrections skipped because the record
    drifted or vanished. `fetch(collection, key)` returns the stored doc."""
    updates: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for key, c in corrections.items():
        wanted = {f: v for f, v in (c.get("fields") or {}).items()
                  if f in fields and v.get("confidence") == "high"}
        if not wanted:
            continue
        for coll in c.get("collections") or ["documents"]:
            doc = fetch(coll, key)
            if doc is None:
                skipped.append(f"{coll}/{key}: not found")
                continue
            new: Dict[str, Any] = {}
            previous: Dict[str, Any] = {}
            for f, v in wanted.items():
                if not _same(doc.get(f), v.get("old")):
                    skipped.append(f"{coll}/{key}.{f}: stored value changed since the report")
                    continue
                new[f] = v.get("new")
                previous[f] = doc.get(f)
            if new:
                updates.append({"collection": coll, "key": key, "set": new,
                                "previous": previous,
                                "source_path": c.get("source_path"),
                                "corpus": c.get("corpus"),
                                "n_passages": c.get("n_passages", 0)})
    return updates, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input", nargs="?", default=str(DEFAULT_INPUT))
    ap.add_argument("--fields", default=",".join(FIELDS),
                    help="comma-separated subset of " + ", ".join(FIELDS))
    ap.add_argument("--apply", action="store_true",
                    help="write to ArangoDB (default: dry run)")
    ap.add_argument("--revert", metavar="BACKUP",
                    help="restore the values saved in a backup file")
    args = ap.parse_args()

    from app.core.database import get_arango_db
    db = get_arango_db().db

    def fetch(coll: str, key: str):
        return db.collection(coll).get(key)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if args.revert:
        backup = json.loads(Path(args.revert).read_text())
        print(f"revert: {len(backup['updates'])} documents from {args.revert}")
        if not args.apply:
            print("dry run — nothing written. Add --apply to restore.")
            return 0
        for u in backup["updates"]:
            db.collection(u["collection"]).update(
                {"_key": u["key"], **u["previous"], "citation_correction": None},
                keep_none=True)
        print("restored.")
        return 0

    fields = tuple(f.strip() for f in args.fields.split(",") if f.strip())
    unknown = set(fields) - set(FIELDS)
    if unknown:
        ap.error(f"unknown field(s): {', '.join(sorted(unknown))}")
    data = json.loads(Path(args.input).read_text())
    updates, skipped = plan(data["corrections"], fields, fetch)

    by_field = Counter(f for u in updates for f in u["set"])
    by_coll = Counter(u["collection"] for u in updates)
    passages = sum(u["n_passages"] for u in updates if u["collection"] == "documents")
    print(f"{'APPLY' if args.apply else 'DRY RUN'} — fields: {', '.join(fields)}")
    print(f"  documents to update: {dict(by_coll)}")
    print(f"  field changes: {dict(by_field)}")
    print(f"  evidence passages whose citation changes: {passages}")
    print(f"  skipped: {len(skipped)}")
    for s in skipped[:20]:
        print(f"    {s}")
    print("  sample:")
    for u in updates[:15]:
        for f, v in u["set"].items():
            print(f"    {u['collection']}/{u['key']} [{u['corpus']}] {f}: "
                  f"{str(u['previous'].get(f))[:60]!r} -> {str(v)[:60]!r}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan_path = OUT_DIR / f"citation_corrections.plan.{stamp}.json"
    plan_path.write_text(json.dumps({"updates": updates, "skipped": skipped},
                                    indent=1, default=str))
    print(f"  plan written to {plan_path}")

    if not args.apply:
        print("dry run — nothing written. Add --apply to write these changes.")
        return 0

    backup_path = OUT_DIR / f"citation_corrections.backup.{stamp}.json"
    backup_path.write_text(json.dumps({"updates": updates}, indent=1,
                                      default=str))
    print(f"backup of the previous values: {backup_path}")
    now = datetime.now(timezone.utc).isoformat()
    for u in updates:
        db.collection(u["collection"]).update(
            {"_key": u["key"], **u["set"],
             "citation_correction": {"at": now, "source": SOURCE,
                                     "fields": sorted(u["set"])}},
            keep_none=True)
    print(f"applied {len(updates)} document updates. Passage citations pick "
          "them up within 15 minutes, or at the next restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
