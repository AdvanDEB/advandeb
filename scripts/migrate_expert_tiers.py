#!/usr/bin/env python
"""Stamp explicit tiers on the existing DEB expert panel.

`tier_of` fails toward `contributor` when no tier is set, because inferring
panel membership from a role would let a future account silently join the
measured panel (docs/10 section 1). That safe default is only safe if the
people who *are* the panel are stamped explicitly — which is this script.

The eight named DEB experts plus the administrator are the panel the comparison
was designed around. Everyone else must be assigned a tier at approval.

Idempotent. Never downgrades an explicitly-set tier.

Usage:
    conda run -n advandeb python scripts/migrate_expert_tiers.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

# The panel, by the name on their account. Matched case-insensitively on
# full_name; anyone not listed keeps whatever tier they already have.
PANEL_NAMES = {
    "domagoj hackenberger", "tin", "suncana", "sunčana", "ines",
    "jasminka", "jadranka", "ivana", "tamara", "branimir",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from pymongo import MongoClient
    url = os.environ.get("MONGODB_URI") or os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
    dbn = os.environ.get("MONGODB_DB_NAME") or "advandeb"
    db = MongoClient(url)[dbn]

    now = datetime.now(timezone.utc)
    stamped = skipped = already = 0
    for u in db.users.find({}, {"full_name": 1, "email": 1, "tier": 1, "roles": 1}):
        name = (u.get("full_name") or "").strip().lower()
        if u.get("tier"):
            already += 1
            continue
        if name not in PANEL_NAMES:
            print(f"  skip (not a listed panel member): {u.get('full_name')!r}")
            skipped += 1
            continue
        stamped += 1
        if not args.dry_run:
            db.users.update_one({"_id": u["_id"]}, {"$set": {
                "tier": "panel",
                "approval": {"by": "migration", "at": now, "tier": "panel",
                             "note": "founding DEB expert panel, pre-tiering"},
            }})
        print(f"  panel: {u.get('full_name')}")

    print(f"\nstamped={stamped} already_tiered={already} skipped={skipped}"
          + ("  [DRY RUN]" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
