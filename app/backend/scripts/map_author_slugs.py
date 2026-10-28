#!/usr/bin/env python3
"""Link user accounts to the `authored_by` slugs their stylized facts carry.

Dry run by default: prints what it would change and what the change does to
the queue, and writes nothing. Pass ``--apply`` to write.

Why this exists. Stylized facts and queue items name their authors by slug —
in production exactly two: ``tin_klanjscek`` (facts 1201-1236) and
``advandeb_workshop_2025`` (1237-1262). The conflict-of-interest exclusion
compared those slugs with user ObjectIds, which never match, and its fallback
(``users.authored_sf_numbers``) is set only at enrolment approval, which no
current expert went through. So every author was being served their own facts.
The exclusion now reads ``users.author_slugs``; this script fills it.

Which account answers to which slug is not something to infer. In particular,
mapping workshop participants to the group slug ``advandeb_workshop_2025``
excludes each of them from all 26 workshop facts, not only the ones they
personally formulated — a deliberate choice, made by a person, recorded here.

Usage (from app/backend/), mapping by account email:

    conda run -n advandeb python scripts/map_author_slugs.py --db advandeb \\
        --map tin@irb.hr=tin_klanjscek \\
        --map someone@irb.hr=advandeb_workshop_2025

    # ...review the dry run, then the same command with --apply

``--db`` has no default on purpose: a default is not a guard (see
app/core/dbguard.py), and this script is meant to be pointed at production
deliberately or not at all.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

from pymongo import MongoClient


def _parse_maps(pairs):
    out = defaultdict(set)
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"--map expects email=slug, got {p!r}")
        email, slug = (x.strip() for x in p.split("=", 1))
        if not email or not slug:
            raise SystemExit(f"--map expects email=slug, got {p!r}")
        out[email.lower()].add(slug)
    return out


def _report_coverage(db, slug_holders, panel_users):
    """What the mapping does to the queue: for each authored slug, how many
    panel experts remain eligible, against what the queue requires."""
    print("\nEffect on the queue (panel experts with the elicitation capability):")
    eligible_total = len(panel_users)
    for slug in sorted(db.stylized_facts.distinct("authored_by")):
        excluded = slug_holders.get(slug, set()) & panel_users
        items = list(db.elicitation_queue.find(
            {"authored_by": slug}, {"task": 1, "n_required": 1}))
        need = max((int(q.get("n_required", 1)) for q in items), default=0)
        ev = [q for q in items if q.get("task") == "evidence"]
        ev_need = max((int(q.get("n_required", 1)) for q in ev), default=0)
        left = eligible_total - len(excluded)
        flag = "  <-- below n_required" if left < need else ""
        print(f"  {slug}: {len(excluded)} panel expert(s) excluded, "
              f"{left} eligible; {len(items)} queue items "
              f"({len(ev)} evidence, n_required up to {ev_need}; "
              f"all tasks up to {need}){flag}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Map user accounts to authored_by slugs (dry run unless --apply).")
    ap.add_argument("--db", required=True,
                    help="database name, e.g. advandeb — no default, deliberately")
    ap.add_argument("--uri", default=os.environ.get("MONGODB_URI",
                                                    "mongodb://localhost:27017"))
    ap.add_argument("--map", action="append", default=[], metavar="EMAIL=SLUG",
                    help="link the account with this email to this slug "
                         "(repeatable; several slugs per account allowed)")
    ap.add_argument("--apply", action="store_true",
                    help="write the mapping; without it nothing is written")
    args = ap.parse_args()

    db = MongoClient(args.uri, serverSelectionTimeoutMS=3000)[args.db]
    known = set(db.stylized_facts.distinct("authored_by"))
    wanted = _parse_maps(args.map)

    print(f"database: {args.db}   mode: {'APPLY' if args.apply else 'dry run'}")
    print(f"authored_by slugs in stylized_facts: {sorted(known) or '(none)'}")
    for slug in sorted(known):
        nums = sorted(int(f["sf_number"]) for f in db.stylized_facts.find(
            {"authored_by": slug}, {"sf_number": 1}))
        span = f"{nums[0]}-{nums[-1]}" if nums else "-"
        print(f"  {slug}: {len(nums)} facts ({span})")

    users = list(db.users.find({}, {"email": 1, "full_name": 1, "tier": 1,
                                    "roles": 1, "capabilities": 1,
                                    "author_slugs": 1,
                                    "authored_sf_numbers": 1}))
    by_email = {(u.get("email") or "").lower(): u for u in users}

    print("\nCurrent accounts:")
    for u in sorted(users, key=lambda u: (u.get("email") or "")):
        print(f"  {u.get('email')!s:32} {u.get('full_name')!s:24} "
              f"tier={u.get('tier')!s:11} author_slugs={u.get('author_slugs') or []} "
              f"authored_sf_numbers={len(u.get('authored_sf_numbers') or [])}")

    problems = []
    plan = []
    for email, slugs in sorted(wanted.items()):
        u = by_email.get(email)
        if not u:
            problems.append(f"no account with email {email}")
            continue
        unknown = sorted(slugs - known)
        if unknown:
            problems.append(f"{email}: slug(s) {unknown} appear on no stylized fact")
            continue
        have = set(u.get("author_slugs") or [])
        add = sorted(slugs - have)
        plan.append((u, add, sorted(have | slugs)))

    print("\nPlanned changes:")
    if not plan:
        print("  (none)")
    for u, add, after in plan:
        verb = f"add {add}" if add else "already mapped — no change"
        print(f"  {u.get('email')}: {verb}; author_slugs -> {after}")

    # Coverage as it would stand after the change.
    holders = defaultdict(set)
    for u in users:
        for s in u.get("author_slugs") or []:
            holders[s].add(u["_id"])
    for u, _add, after in plan:
        for s in after:
            holders[s].add(u["_id"])
    panel = {u["_id"] for u in users
             if u.get("tier") == "panel"
             and ("sf_elicitation" in (u.get("capabilities") or [])
                  or "administrator" in (u.get("roles") or []))}
    _report_coverage(db, holders, panel)

    if problems:
        print("\nRefusing — fix these first:")
        for p in problems:
            print(f"  {p}")
        return 2
    if not args.apply:
        print("\nDry run: nothing written. Re-run with --apply to write.")
        return 0

    now = datetime.now(timezone.utc)
    for u, add, _after in plan:
        if not add:
            continue
        db.users.update_one(
            {"_id": u["_id"]},
            {"$addToSet": {"author_slugs": {"$each": add}},
             "$set": {"updated_at": now}})
        print(f"  wrote {u.get('email')}: +{add}")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
