#!/usr/bin/env python
"""Quantify reproduction-abstract coverage: abstracts vs embedded chunks vs index cache."""
import os, datetime
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "app", "backend", ".env"))
from pymongo import MongoClient
from bson import ObjectId

cl = MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017"))
db = cl["deb_abstracts_reproduction"]

print("== reproduction coverage ==", flush=True)
n_abs = db.abstracts.estimated_document_count()
n_chunks = db.abstract_chunks.estimated_document_count()
print(f"abstracts:        {n_abs:,}", flush=True)
print(f"abstract_chunks:  {n_chunks:,}", flush=True)
print(f"index cache:      4,401,990 (Jan-21 snapshot)", flush=True)

mx = db.abstract_chunks.find_one(sort=[("chunk_id", -1)])
print(f"max chunk_id seen: {mx.get('chunk_id')}", flush=True)
multi = db.abstract_chunks.count_documents({"chunk_id": {"$gt": 0}})
print(f"chunks with chunk_id>0 (multi-chunk abstracts): {multi:,}", flush=True)

after = db.abstract_chunks.count_documents(
    {"_id": {"$gte": ObjectId.from_datetime(datetime.datetime(2026, 1, 21, 8, 22))}})
print(f"chunks created AFTER cache snapshot (missing from 20GB index): {after:,}", flush=True)

# distinct embedded abstracts (exact, via aggregation — may take a few minutes over 4.4M)
print("counting distinct embedded abstracts (doc_id) via aggregation ...", flush=True)
res = list(db.abstract_chunks.aggregate(
    [{"$group": {"_id": "$doc_id"}}, {"$count": "n"}], allowDiskUse=True))
distinct = res[0]["n"] if res else 0
print(f"distinct abstracts with >=1 embedded chunk: {distinct:,}", flush=True)
missing = n_abs - distinct
print(f"abstracts NEVER embedded: {missing:,}  (~{100*missing/n_abs:.1f}%)", flush=True)
print("DONE", flush=True)
