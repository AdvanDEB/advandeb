#!/usr/bin/env python
"""Seed stylized-fact collection v1.0 into MongoDB.

Brings the app's ``stylized_facts`` collection up to the canonical artefact
built in ``advandeb_methods/data/collection/collection_v1.0.json``:

* adds the 26 AdvanDEB workshop facts as 1237-1262 (previously they lived only
  inside ``analyze_sf_support.py`` and were not in the collection at all);
* adds ``statement_sha256`` so a score attaches to an exact wording rather than
  to a fact number whose text can drift — it already drifted once;
* adds ``provenance_type``, ``source_citation``, ``authored_by`` and the legacy
  1-100 assessment carried over from the older stylized_DEB pipeline.

Additive and idempotent. The previous category value is preserved in
``legacy_category`` rather than discarded.

Usage:
    conda run -n advandeb python scripts/seed_collection_v1.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ARTEFACT = (Path.home() / "dev/advandeb_methods/data/collection"
            / "collection_v1.0.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artefact", type=Path, default=ARTEFACT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.artefact.exists():
        print(f"artefact not found: {args.artefact}", file=sys.stderr)
        print("build it with: python experiments/build_collection.py",
              file=sys.stderr)
        return 1

    from pymongo import MongoClient
    payload = json.loads(args.artefact.read_text())
    facts = payload["facts"]
    manifest = payload["manifest"]
    print(f"artefact: {len(facts)} facts, manifest "
          f"{manifest['manifest_sha256'][:16]}, version "
          f"{manifest['collection_version']}")

    url = os.environ.get("MONGODB_URI") or os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
    dbn = os.environ.get("MONGODB_DB_NAME") or "advandeb"
    db = MongoClient(url)[dbn]

    before = db.stylized_facts.count_documents({})
    stats = Counter()
    now = datetime.now(timezone.utc)

    for f in facts:
        n = f["sf_number"]
        existing = db.stylized_facts.find_one(
            {"$or": [{"sf_number": n}, {"sf_number": str(n)}]})
        update = {
            "statement": f["statement"],
            "statement_sha256": f["statement_sha256"],
            "collection_version": f["collection_version"],
            "category": f["category"],
            "provenance_type": f["provenance_type"],
            "source_citation": f.get("source_citation"),
            "authored_by": f.get("authored_by", []),
            "updated_at": now,
        }
        if f.get("legacy_assessment"):
            update["legacy_assessment"] = f["legacy_assessment"]

        if existing:
            if existing.get("category") and existing["category"] != f["category"]:
                update["legacy_category"] = existing["category"]
            if existing.get("statement", "").strip() != f["statement"]:
                stats["statement_changed"] += 1
            stats["updated"] += 1
            if not args.dry_run:
                db.stylized_facts.update_one({"_id": existing["_id"]},
                                             {"$set": update})
        else:
            stats["inserted"] += 1
            if not args.dry_run:
                db.stylized_facts.insert_one({
                    "sf_number": n, "status": "published",
                    "created_at": now, **update})

    after = before if args.dry_run else db.stylized_facts.count_documents({})
    print(f"before={before} after={after} "
          f"inserted={stats['inserted']} updated={stats['updated']} "
          f"statement_text_changed={stats['statement_changed']}"
          + ("  [DRY RUN]" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
