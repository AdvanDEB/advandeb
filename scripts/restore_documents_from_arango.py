#!/usr/bin/env python
"""Restore `advandeb.documents` from the ArangoDB `document_meta` mirror.

Written after the collection was dropped by a test that used
`os.environ.setdefault("MONGODB_DB_NAME", ...)` while the real name was already
exported into the environment — so the scratch redirect silently did nothing and
the drop hit production.

Recovery is possible because `document_meta._key` **is** the original Mongo
ObjectId hex, so documents come back with their original `_id` and the 28,309
facts that reference them stay linked. Restoring with fresh ids would have
orphaned every one of those references.

What comes back: title, doi, authors, year, journal, abstract, source_type,
processing_status, num_chunks, num_facts, general_domain and the flag fields.
`source_path` is recovered from `ingestion_jobs` where a job carries it.

What does NOT come back here: `content`, the full extracted text. It is not
mirrored in `document_meta`. It is recoverable separately from
`deb_literature_review.documents.extracted_text` or by re-extracting the PDFs in
`papers/`, and is backfilled by `--with-content`.

Arango stringified everything during the Mongo->Arango migration ("2021", "9",
"None"), so values are coerced back rather than restored as strings.

    conda run -n advandeb python scripts/restore_documents_from_arango.py --dry-run
    conda run -n advandeb python scripts/restore_documents_from_arango.py
    conda run -n advandeb python scripts/restore_documents_from_arango.py --with-content
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any, Optional


def coerce(v: Any) -> Any:
    """Undo the migration's stringification."""
    if v in ("None", "null", "", None):
        return None
    return v


def as_int(v: Any) -> Optional[int]:
    v = coerce(v)
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def as_dt(v: Any) -> Any:
    v = coerce(v)
    if not isinstance(v, str):
        return v
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--with-content", action="store_true",
                    help="also backfill extracted text from deb_literature_review")
    args = ap.parse_args()

    from arango import ArangoClient
    from bson import ObjectId
    from pymongo import MongoClient

    adb = ArangoClient(hosts=os.environ.get("ARANGO_URL") or "http://localhost:8529").db(
        os.environ.get("ARANGO_DB") or "advandeb_kb",
        username=os.environ.get("ARANGO_USERNAME") or "root",
        password=os.environ.get("ARANGO_PASSWORD") or "")

    murl = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
    mdb = MongoClient(murl)["advandeb"]

    before = mdb.documents.count_documents({})
    print(f"advandeb.documents before: {before}")

    # source_path, from the ingestion job that created each document
    src_by_doc = {}
    for j in mdb.ingestion_jobs.find(
            {"document_id": {"$exists": True, "$ne": None}},
            {"document_id": 1, "source_path_or_url": 1}):
        if j.get("source_path_or_url"):
            src_by_doc[str(j["document_id"])] = j["source_path_or_url"]
    print(f"source paths recoverable from ingestion_jobs: {len(src_by_doc)}")

    content_by_name = {}
    if args.with_content:
        lit = MongoClient(murl)["deb_literature_review"]
        for d in lit.documents.find({}, {"filename": 1, "extracted_text": 1}):
            if d.get("filename") and d.get("extracted_text"):
                content_by_name[d["filename"].lower()] = d["extracted_text"]
        print(f"extracted texts available for backfill: {len(content_by_name)}")

    rows = list(adb.aql.execute("FOR d IN document_meta RETURN d"))
    print(f"document_meta rows: {len(rows)}")

    restored = skipped = with_content = 0
    for r in rows:
        key = r.get("_key")
        try:
            oid = ObjectId(key)
        except Exception:
            skipped += 1
            continue
        if mdb.documents.find_one({"_id": oid}, {"_id": 1}):
            skipped += 1
            continue

        doc = {
            "_id": oid,
            "title": coerce(r.get("title")),
            "doi": coerce(r.get("doi")),
            "authors": coerce(r.get("authors")),
            "year": as_int(r.get("year")),
            "journal": coerce(r.get("journal")),
            "abstract": coerce(r.get("abstract")),
            "source_type": coerce(r.get("source_type")) or "pdf_local",
            "processing_status": coerce(r.get("processing_status")) or "completed",
            "num_chunks": as_int(r.get("num_chunks")),
            "num_facts": as_int(r.get("num_facts")),
            "general_domain": coerce(r.get("general_domain")),
            "potentially_irrelevant": coerce(r.get("potentially_irrelevant")),
            "flag_reason": coerce(r.get("flag_reason")),
            "flagged_by": coerce(r.get("flagged_by")),
            "flagged_at": as_dt(r.get("flagged_at")),
            "created_at": as_dt(r.get("created_at")),
            "updated_at": as_dt(r.get("updated_at")),
            "restored_from": "arango:document_meta",
        }
        sp = src_by_doc.get(key)
        if sp:
            doc["source_path"] = sp
        if content_by_name and sp:
            base = os.path.basename(str(sp)).lower()
            if base in content_by_name:
                doc["content"] = content_by_name[base]
                with_content += 1

        restored += 1
        if not args.dry_run:
            mdb.documents.insert_one(doc)

    after = before if args.dry_run else mdb.documents.count_documents({})
    print(f"\nrestored={restored} skipped={skipped} content_backfilled={with_content}")
    print(f"advandeb.documents after: {after}"
          + ("  [DRY RUN]" if args.dry_run else ""))

    if not args.dry_run:
        linked = 0
        ids = {d["_id"] for d in mdb.documents.find({}, {"_id": 1})}
        for did in mdb.facts.distinct("document_id"):
            if did in ids:
                linked += 1
        print(f"fact->document links resolving: {linked} "
              f"of {len(mdb.facts.distinct('document_id'))} distinct ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
