#!/usr/bin/env python3
"""
Repair the retrieval corpus: re-chunk the full-text library with the fixed
chunker, retire the duplicate chunk lineages, chunk the abstracts that were
never embedded, and rebuild the vector store from ArangoDB ``chunks``.

Why
---
* Every full-text chunk was made by the old chunker, which dropped newline and
  space separators ("structural volume andthe reserve density").
* The ~1,250 library PDFs are in the vector store twice (a ``doc_<hash>``
  lineage and a MongoDB-ObjectId lineage, ~586k vectors), while the ArangoDB
  ``documents`` those PDFs belong to have 263,691 chunks and no vectors at all.
  Retrieval returns the same passage under two ids.
* About a third of the ``doc_<hash>`` vectors (~86k) are in chroma.sqlite3 but
  missing from the HNSW index: vector search never returns them, and any
  metadata-filtered query touching them fails with "Error finding id".
* Only 600,754 of 3,899,789 documents (15.4%) are embedded; ~3.28M OpenAlex
  abstracts have no chunks, so neither search arm can find them.

How
---
ArangoDB ``chunks`` becomes the single source of truth and the vector store is
rebuilt from it, fresh, in a separate directory (blue/green). ChromaDB runs
embedded inside the retrieval agent and the app backend, so it is never
written by a second process while they run: the new store is moved into place
in a short maintenance window with both stopped, and the old one is kept for
an instant rollback.

Arango writes happen during the build — Arango is a server, and the keyword
arm can use new chunks at once. Every chunk, edge and document this script
writes carries ``repair_run: <run id>``, so a run can be found and undone
without a restore.

Phases, in order (each resumable; checkpoints live in --state-dir):

  plan                      read-only inventory + time/RAM/disk estimates (default)
  rechunk-library           re-chunk library documents (documents.content) with the
                            fixed chunker; replace their Arango chunks + edges
  chunk-abstracts           chunk the un-embedded abstracts into Arango chunks + edges;
                            documents get embedding_status "chunked"
  build-store               embed every Arango chunk except the retired duplicate
                            lineages into a NEW ChromaDB store at --work-chroma
  verify                    counts + spot searches on the new store
  swap                      (services stopped) check the live store is unchanged since
                            build-store began, move it aside, move the new store in;
                            then flip this run's "chunked" documents to "embedded"
  retire-duplicates-arango  (after swap) delete the duplicate-lineage chunks + edges

Nothing is written without --apply. Writes to a production Arango database
need --production and a successful ``arango:<db>`` backup from the last 26 h
(advandeb_kb.backup_guard.require_recent_backup); the swap needs a recent
``chroma`` backup.

Retired: every duplicate-lineage document of a paper whose library document
was re-chunked. Papers that exist only in the duplicate lineages (no library
document with text) keep exactly one copy — the ObjectId lineage if there is
one, it is the intact one — so no paper drops out of retrieval.

Do not run embed_reproduction_abstracts.py or batch PDF ingestion while a
repair is in progress: they write to the live store, and swap refuses when the
live store changed.

Usage:
    cd /home/adeb/dev/advandeb && set -a && . app/backend/.env && set +a
    PY=~/miniforge3/envs/advandeb/bin/python
    $PY knowledge-builder/scripts/repair_corpus.py plan
    $PY knowledge-builder/scripts/repair_corpus.py rechunk-library --apply --production
    ...
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from advandeb_kb.config.settings import settings  # noqa: E402

SCRATCH_MARKERS = ("scratch", "_test", "test_", "sandbox", "tmp")
LIBRARY_DOMAIN = "deb"
ABSTRACT_DOMAIN = "reproduction"
CHUNKER_TAG = "offsets-v2"

# Throughputs measured on this machine (see the retrieval quality report),
# used by `plan`.
EMBED_CHUNKS_PER_S = 1000.0        # all-MiniLM-L6-v2 on one shared Quadro RTX 8000
CHROMA_UPSERT_PER_S = 450.0        # fresh store, 5,000-vector batches with documents
                                   # (1,100/s without: the documents' FTS index is the cost)
CHUNKS_PER_ABSTRACT = 3.7          # 2,201,278 chunks / 599,538 embedded abstracts
LIBRARY_CHARS_PER_CHUNK = 458      # 116.7M chars -> 254,806 chunks (fixed chunker)
RAM_BYTES_PER_VECTOR = 2000        # vectors + HNSW graph + page cache, measured growth
DISK_BYTES_PER_VECTOR = 6200       # 17.4 GB / 2.81M in the current store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def is_scratch(db_name: str) -> bool:
    name = db_name.strip().lower()
    return name != "advandeb_kb" and any(m in name for m in SCRATCH_MARKERS)


def file_key(path: Optional[str]) -> str:
    return os.path.basename((path or "").strip()).lower()


class State:
    """A small JSON checkpoint per phase, replaced atomically."""

    def __init__(self, state_dir: Path, phase: str):
        self.path = state_dir / f"{phase}.json"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.data: dict = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, default=str))
        os.replace(tmp, self.path)


def run_id(state_dir: Path) -> str:
    path = state_dir / "run_id"
    if path.exists():
        return path.read_text().strip()
    rid = "repair-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    state_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(rid + "\n")
    return rid


def arango(db_name: str):
    from arango import ArangoClient

    client = ArangoClient(hosts=settings.ARANGO_URL, request_timeout=3600)
    return client.db(db_name, username=settings.ARANGO_USERNAME, password=settings.ARANGO_PASSWORD)


def require_backup(component: str, max_age_hours: float) -> None:
    try:
        from advandeb_kb.backup_guard import require_recent_backup
    except ImportError:
        raise SystemExit("advandeb_kb.backup_guard is not available; cannot check the backup precondition")
    manifest = require_recent_backup(component, max_age_hours=max_age_hours)
    log(f"backup check passed for {component}: {manifest['_path']}")


def guard_arango_writes(args) -> None:
    """Refuse production Arango writes without --production and a recent backup."""
    if not args.apply or is_scratch(args.arango_db):
        return
    if not args.production:
        raise SystemExit(f"refusing to write to production database {args.arango_db!r} without --production")
    require_backup(f"arango:{args.arango_db}", args.backup_max_age_hours)


def chroma_fingerprint(store: Path, locking: bool = True) -> dict:
    """
    Cheap identity of a Chroma store: row count and highest log sequence.

    ``locking=False`` reads without taking any SQLite lock (immutable=1), so it
    cannot contend with the running retrieval agent; use it only for a store no
    one writes to at the time (ingestion paused). The swap re-reads with locks
    once the services are stopped.
    """
    mode = "ro" if locking else "ro&immutable=1"
    con = sqlite3.connect(f"file:{store / 'chroma.sqlite3'}?mode={mode}", uri=True)
    try:
        count, max_seq = con.execute("SELECT COUNT(*), MAX(seq_id) FROM embeddings").fetchone()
        try:
            queue = con.execute("SELECT MAX(seq_id) FROM embeddings_queue").fetchone()[0]
        except sqlite3.Error:
            queue = None
    finally:
        con.close()
    return {"count": count, "max_seq_id": max_seq, "max_queue_seq_id": queue}


def processes_using(path: Path) -> list[str]:
    """Processes (pid + command) holding a file open under ``path``."""
    prefix = str(path.resolve())
    users = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                if os.readlink(f"/proc/{pid}/fd/{fd}").startswith(prefix):
                    cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()[:120]
                    users.append(f"{pid} {cmd}")
                    break
        except OSError:
            continue
    return users


def load_embedder(device: Optional[str]):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.EMBEDDING_MODEL, device=device)


def embed(model, texts: list[str]) -> list[list[float]]:
    return model.encode(texts, batch_size=256, normalize_embeddings=True, convert_to_numpy=True,
                        show_progress_bar=False).tolist()


def batched(items: list, n: int) -> Iterable[list]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


# ---------------------------------------------------------------------------
# Inventory: library documents and the duplicate lineages
# ---------------------------------------------------------------------------

LINEAGE_AQL = """
FOR c IN chunks
    FILTER !STARTS_WITH(c.document_id, "W")
    COLLECT doc = c.document_id AGGREGATE source = MAX(c.source_path), n = COUNT(1)
    RETURN {doc, source, n}
"""


def _lineage(doc_id: str, library_keys: set) -> str:
    # By document, not by chunk fields: re-chunked library chunks carry a
    # source_path too, which is what used to tell the ObjectId lineage apart.
    if doc_id in library_keys:
        return "library"
    return "doc_hash" if doc_id.startswith("doc_") else "objectid"


def inventory(db, rechunked: Optional[set] = None) -> dict:
    """
    Library documents, duplicate-lineage documents, and which of the latter
    to retire. With ``rechunked`` (keys done by rechunk-library) a paper counts
    as covered only if its library document was actually re-chunked; without
    it, any library document with text covers its paper (the plan view).
    """
    library = list(db.aql.execute(
        "FOR d IN documents FILTER d.source_type == 'pdf_local' "
        "RETURN {k: d._key, p: d.source_path, n: LENGTH(d.content)}"))
    covered = {
        file_key(d["p"]) for d in library
        if d["n"] and (rechunked is None or d["k"] in rechunked)
    }
    library_keys = {d["k"] for d in library}
    lineages: dict[str, dict] = {}
    orphans: dict[str, list[dict]] = {}
    retire: list[str] = []
    for row in db.aql.execute(LINEAGE_AQL):
        row["lineage"] = _lineage(row["doc"], library_keys)
        s = lineages.setdefault(row["lineage"], {"docs": 0, "chunks": 0, "retire_docs": 0, "retire_chunks": 0})
        s["docs"] += 1
        s["chunks"] += row["n"]
        if row["lineage"] == "library":
            continue
        if file_key(row["source"]) in covered:
            retire.append(row["doc"])
            s["retire_docs"] += 1
            s["retire_chunks"] += row["n"]
        else:
            orphans.setdefault(file_key(row["source"]), []).append(row)
    # A paper only the duplicate lineages hold keeps one copy: the ObjectId
    # lineage (intact) over doc_hash, then the one with most chunks.
    for rows in orphans.values():
        rows.sort(key=lambda r: (r["lineage"] != "objectid", -r["n"]))
        for r in rows[1:]:
            retire.append(r["doc"])
            lineages[r["lineage"]]["retire_docs"] += 1
            lineages[r["lineage"]]["retire_chunks"] += r["n"]
    return {
        "library_docs": len(library),
        "library_docs_with_text": sum(1 for d in library if d["n"]),
        "library_chars": sum(d["n"] or 0 for d in library),
        "lineages": lineages,
        "orphan_papers": len(orphans),
        "retire": retire,
    }


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

def cmd_plan(args) -> None:
    db = arango(args.arango_db)
    inv = inventory(db)
    pending_abstracts = next(iter(db.aql.execute(
        "RETURN LENGTH(FOR d IN documents FILTER d.source_type == 'web' AND d.embedding_status == null "
        "AND LENGTH(d.abstract) > 50 RETURN 1)")))
    abstract_chunks = next(iter(db.aql.execute(
        "RETURN LENGTH(FOR c IN chunks FILTER STARTS_WITH(c.document_id, 'W') RETURN 1)")))
    # Only stat() the live store: plan never opens it.
    live = Path(settings.CHROMA_PERSIST_DIR)
    live_bytes = sum(f.stat().st_size for f in live.rglob("*") if f.is_file())

    lib_chunks = inv["library_chars"] / LIBRARY_CHARS_PER_CHUNK
    new_abs_chunks = pending_abstracts * CHUNKS_PER_ABSTRACT
    kept_dups = sum(s["chunks"] - s["retire_chunks"] for l, s in inv["lineages"].items() if l != "library")
    vectors = lib_chunks + kept_dups + abstract_chunks + new_abs_chunks
    rate = min(EMBED_CHUNKS_PER_S, CHROMA_UPSERT_PER_S)

    print(json.dumps({k: v for k, v in inv.items() if k != "retire"}, indent=1))
    print(f"live store: {live_bytes / 1e9:.1f} GB on disk")
    print(f"abstracts to chunk: {pending_abstracts:,} (~{new_abs_chunks / 1e6:.1f}M chunks); "
          f"existing abstract chunks: {abstract_chunks:,}")
    print()
    print(f"rechunk-library   ~{lib_chunks / 1e3:.0f}k chunks into Arango                  minutes")
    print(f"chunk-abstracts   ~{new_abs_chunks / 1e6:.1f}M chunks into Arango                 "
          f"~{new_abs_chunks / 20000 / 60:.0f} min")
    print(f"build-store       {vectors / 1e6:.1f}M vectors at ~{rate:.0f}/s                    "
          f"~{vectors / rate / 3600:.1f} h  (library + kept orphans + all abstracts)")
    print(f"  of which without new abstracts: {(vectors - new_abs_chunks) / 1e6:.2f}M vectors, "
          f"~{(vectors - new_abs_chunks) / rate / 3600:.1f} h")
    print(f"swap              2 renames (seconds) + status flip of {pending_abstracts:,} documents")
    print(f"retire-dups       {sum(s['retire_chunks'] for s in inv['lineages'].values()) / 1e3:.0f}k "
          f"Arango chunks + edges")
    print()
    print(f"new store: ~{vectors * DISK_BYTES_PER_VECTOR / 1e9:.0f} GB disk; HNSW ~"
          f"{vectors * RAM_BYTES_PER_VECTOR / 1e9:.0f} GB RAM in EACH process that opens it "
          f"(retrieval agent, app backend); the old store ({live_bytes / 1e9:.0f} GB) is kept for rollback")


# ---------------------------------------------------------------------------
# rechunk-library / chunk-abstracts (Arango writes)
# ---------------------------------------------------------------------------

def _arango_records(doc: dict, chunks, rid: str, domain: str, now: str) -> tuple[list, list]:
    arango_chunks, edges = [], []
    for c in chunks:
        arango_chunks.append({
            "_key": c.chunk_id, "chunk_id": c.chunk_id, "document_id": doc["_key"],
            "chunk_index": c.chunk_index, "text": c.text,
            "char_start": c.char_start, "char_end": c.char_end,
            "general_domain": domain, "source_path": doc.get("source_path"),
            "chunker": CHUNKER_TAG, "created_at": now, "repair_run": rid,
        })
        edges.append({"_key": f"{c.chunk_id}_belongs", "_from": f"chunks/{c.chunk_id}",
                      "_to": f"documents/{doc['_key']}", "repair_run": rid})
    return arango_chunks, edges


REMOVE_STALE_AQL = """
FOR c IN chunks
    FILTER c.document_id == @doc AND c._key NOT IN @keep
    LET cid = c._id
    REMOVE c IN chunks
    FOR e IN chunk_belongs_to FILTER e._from == cid
    REMOVE e IN chunk_belongs_to
"""


def cmd_rechunk_library(args) -> None:
    from advandeb_kb.services.chunking_service import ChunkingService

    guard_arango_writes(args)
    db = arango(args.arango_db)
    rid = run_id(Path(args.state_dir))
    state = State(Path(args.state_dir), "rechunk-library")
    done = set(state.data.get("done", []))
    keys = list(db.aql.execute(
        "FOR d IN documents FILTER d.source_type == 'pdf_local' AND LENGTH(d.content) > 0 "
        "SORT d._key RETURN d._key"))
    todo = [k for k in keys if k not in done][: args.limit or None]
    log(f"library documents with text: {len(keys)}, done: {len(done)}, this run: {len(todo)}")
    if not args.apply:
        log("dry run: nothing written")
        return
    chunker = ChunkingService(chunk_size=512, overlap=128)
    n_chunks = state.data.get("chunks", 0)
    for i, key in enumerate(todo, 1):
        doc = db.collection("documents").get(key)
        now = datetime.now(timezone.utc).isoformat()
        chunks = chunker.chunk_document(doc["content"], key)
        a_chunks, edges = _arango_records(doc, chunks, rid, LIBRARY_DOMAIN, now)
        db.collection("chunks").import_bulk(a_chunks, on_duplicate="replace", halt_on_error=True)
        db.collection("chunk_belongs_to").import_bulk(edges, on_duplicate="replace", halt_on_error=True)
        db.aql.execute(REMOVE_STALE_AQL, bind_vars={"doc": key, "keep": [c["_key"] for c in a_chunks]})
        db.collection("documents").update({
            "_key": key, "num_chunks": len(chunks), "chunker": CHUNKER_TAG,
            "repair_run": rid, "updated_at": now,
        })
        done.add(key)
        n_chunks += len(chunks)
        if i % 25 == 0 or i == len(todo):
            state.data.update({"done": sorted(done), "chunks": n_chunks, "run_id": rid})
            state.save()
            log(f"{len(done)}/{len(keys)} library documents, {n_chunks:,} chunks")


def cmd_chunk_abstracts(args) -> None:
    from advandeb_kb.services.chunking_service import ChunkingService

    guard_arango_writes(args)
    db = arango(args.arango_db)
    rid = run_id(Path(args.state_dir))
    state = State(Path(args.state_dir), "chunk-abstracts")
    last_key = state.data.get("last_key", "")
    pending = next(iter(db.aql.execute(
        "RETURN LENGTH(FOR d IN documents FILTER d.source_type == 'web' AND d.embedding_status == null "
        "AND LENGTH(d.abstract) > 50 RETURN 1)")))
    log(f"abstracts pending: {pending:,}" + (f"; resuming after {last_key}" if last_key else ""))
    if not args.apply:
        log("dry run: nothing written")
        return
    chunker = ChunkingService(chunk_size=512, overlap=128)
    started = time.time()
    n_docs, n_chunks = state.data.get("docs", 0), state.data.get("chunks", 0)
    budget = args.limit or float("inf")
    run_docs = 0
    while run_docs < budget:
        # Primary-index range scan in key order; the last key is the checkpoint.
        docs = list(db.aql.execute(
            "FOR d IN documents FILTER d._key > @last SORT d._key "
            "FILTER d.source_type == 'web' AND d.embedding_status == null AND LENGTH(d.abstract) > 50 "
            "LIMIT @n RETURN KEEP(d, '_key', 'abstract', 'source_path')",
            bind_vars={"last": last_key, "n": args.batch_size}))
        if not docs:
            break
        now = datetime.now(timezone.utc).isoformat()
        a_chunks, edges, per_doc = [], [], {}
        for d in docs:
            chunks = chunker.chunk_document(d["abstract"], d["_key"])
            ac, e = _arango_records(d, chunks, rid, ABSTRACT_DOMAIN, now)
            a_chunks += ac
            edges += e
            per_doc[d["_key"]] = len(chunks)
        db.collection("chunks").import_bulk(a_chunks, on_duplicate="replace", halt_on_error=True)
        db.collection("chunk_belongs_to").import_bulk(edges, on_duplicate="replace", halt_on_error=True)
        db.aql.execute(
            "FOR k IN ATTRIBUTES(@counts) UPDATE {_key: k, embedding_status: 'chunked', "
            "num_chunks: @counts[k], chunker: @tag, repair_run: @rid, updated_at: @now} IN documents",
            bind_vars={"counts": per_doc, "tag": CHUNKER_TAG, "rid": rid, "now": now})
        last_key = docs[-1]["_key"]
        n_docs += len(docs)
        n_chunks += len(a_chunks)
        run_docs += len(docs)
        state.data.update({"last_key": last_key, "docs": n_docs, "chunks": n_chunks, "run_id": rid})
        state.save()
        el = time.time() - started
        log(f"{n_docs:,} abstracts, {n_chunks:,} chunks; {run_docs / el:.0f} docs/s, "
            f"ETA {(pending - run_docs) / max(1e-9, run_docs / el) / 60:.0f} min")


# ---------------------------------------------------------------------------
# build-store
# ---------------------------------------------------------------------------

BUILD_AQL = """
FOR c IN chunks
    FILTER c._key > @last
    SORT c._key
    LIMIT @n
    LET d = DOCUMENT("documents", c.document_id)
    RETURN {
        id: c._key, text: c.text, document_id: c.document_id,
        chunk_index: c.chunk_index, char_start: c.char_start, char_end: c.char_end,
        general_domain: c.general_domain, source_path: c.source_path,
        title: d.title, year: d.year, doi: d.doi, doc_source_path: d.source_path
    }
"""


def _vector_metadata(row: dict) -> dict:
    domain = row.get("general_domain") or LIBRARY_DOMAIN
    return {
        "document_id": row["document_id"],
        "chunk_index": int(row.get("chunk_index") or 0),
        "char_start": int(row.get("char_start") or 0),
        "char_end": int(row.get("char_end") or 0),
        "general_domain": domain,
        "source_path": row.get("source_path") or row.get("doc_source_path") or "",
        "title": row.get("title") or "",
        "year": int(row.get("year") or 0) if str(row.get("year") or "0").isdigit() else 0,
        "doi": row.get("doi") or "",
    }


def cmd_build_store(args) -> None:
    import chromadb

    db = arango(args.arango_db)
    store = Path(args.work_chroma)
    live = Path(settings.CHROMA_PERSIST_DIR)
    if store.resolve() == live.resolve():
        raise SystemExit("--work-chroma must not be the live store")
    state = State(Path(args.state_dir), "build-store")
    rechunked = set(State(Path(args.state_dir), "rechunk-library").data.get("done", []))
    if "retire" not in state.data:
        if not rechunked:
            log("warning: rechunk-library has not run; no duplicate lineage will be retired")
        inv = inventory(db, rechunked)
        state.data.update({
            "retire": sorted(inv["retire"]),
            "live_fingerprint": chroma_fingerprint(live, locking=False),
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
    retire = set(state.data["retire"])
    total = db.collection("chunks").count()
    log(f"Arango chunks: {total:,}; duplicate-lineage documents skipped: {len(retire):,}; "
        f"resuming after {state.data.get('last_key')!r}" if state.data.get("last_key") else
        f"Arango chunks: {total:,}; duplicate-lineage documents skipped: {len(retire):,}")
    if not args.apply:
        log("dry run: nothing written")
        return
    state.save()
    col = chromadb.PersistentClient(path=str(store)).get_or_create_collection(
        settings.CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"})
    model = load_embedder(args.device)
    last = state.data.get("last_key", "")
    n_vec, n_seen = state.data.get("vectors", 0), state.data.get("seen", 0)
    started, run_vec, run_seen = time.time(), 0, 0
    t_embed = t_wait = 0.0
    # One upsert in flight while the next batch is read and embedded: Chroma
    # (~450 vectors/s with documents) and the GPU (~1000/s) then overlap. The
    # checkpoint only moves past a batch once its upsert has returned.
    upserts = ThreadPoolExecutor(max_workers=1)
    in_flight = None  # (future, checkpoint after it)

    def settle():
        nonlocal in_flight, t_wait
        if in_flight is None:
            return
        future, checkpoint = in_flight
        t = time.time()
        future.result()
        t_wait += time.time() - t
        state.data.update(checkpoint)
        state.save()
        in_flight = None

    while True:
        rows = list(db.aql.execute(BUILD_AQL, bind_vars={"last": last, "n": args.build_batch}))
        if not rows:
            break
        keep = [r for r in rows if r["document_id"] not in retire and (r.get("text") or "").strip()]
        vecs = None
        if keep:
            t = time.time()
            vecs = embed(model, [r["text"] for r in keep])
            t_embed += time.time() - t
        settle()
        last = rows[-1]["id"]
        n_seen += len(rows)
        run_seen += len(rows)
        n_vec += len(keep)
        run_vec += len(keep)
        checkpoint = {"last_key": last, "vectors": n_vec, "seen": n_seen}
        if keep:
            in_flight = (upserts.submit(
                col.upsert, ids=[r["id"] for r in keep], embeddings=vecs,
                documents=[r["text"] for r in keep], metadatas=[_vector_metadata(r) for r in keep],
            ), checkpoint)
        else:
            state.data.update(checkpoint)
            state.save()
        el = time.time() - started
        log(f"{n_seen:,}/{total:,} chunks read, {n_vec:,} vectors; {run_vec / el:.0f} vec/s "
            f"(embedding {t_embed:.0f}s, waiting on upserts {t_wait:.0f}s), "
            f"ETA {(total - n_seen) / (run_seen / el) / 3600:.1f} h")
        if args.limit and run_vec >= args.limit:
            break
    settle()
    upserts.shutdown()
    state.data["done"] = n_seen >= total
    state.save()


# ---------------------------------------------------------------------------
# verify / swap / retire
# ---------------------------------------------------------------------------

def cmd_verify(args) -> None:
    import chromadb

    store = Path(args.work_chroma)
    col = chromadb.PersistentClient(path=str(store)).get_collection(settings.CHROMA_COLLECTION)
    built = State(Path(args.state_dir), "build-store").data
    log(f"new store: {col.count():,} vectors (build-store wrote {built.get('vectors', 0):,}; "
        f"finished: {built.get('done', False)})")
    model = load_embedder(args.device)
    for q in ("energy allocation to reproduction kappa rule",
              "von Bertalanffy growth at abundant food",
              "starvation survival and reserve dynamics"):
        res = col.query(query_embeddings=embed(model, [q]), n_results=5, include=["documents", "metadatas"])
        log(f"{q!r}:")
        for cid, txt in zip(res["ids"][0], res["documents"][0]):
            log(f"   {cid}: {' '.join(txt.split())[:110]}")
    sample = col.get(limit=2000, include=["embeddings"])  # raises on ids missing from HNSW
    log(f"sampled {len(sample['ids'])} ids with embeddings: ok")


def cmd_swap(args) -> None:
    live = Path(settings.CHROMA_PERSIST_DIR)
    work = Path(args.work_chroma)
    built = State(Path(args.state_dir), "build-store").data
    state = State(Path(args.state_dir), "swap")
    rid = run_id(Path(args.state_dir))
    if not state.data.get("moved"):
        if not built.get("done"):
            raise SystemExit("build-store has not finished")
        current = chroma_fingerprint(live)
        log(f"live store now {current}; when build-store began {built.get('live_fingerprint')}")
        if current != built.get("live_fingerprint"):
            raise SystemExit("the live store changed since build-store began (new ingestion?). Backfill "
                             "those chunks into Arango (backfill_chunks_chroma_to_arango.py) and re-run "
                             "build-store to pick them up before swapping.")
        users = processes_using(live) + processes_using(work)
        if users:
            raise SystemExit("stop these processes first (retrieval agent, app backend):\n  " + "\n  ".join(users))
        aside = live.with_name(live.name + ".pre-" + rid)
        log(f"{'will' if args.apply else 'would'} move {live} -> {aside} and {work} -> {live}")
        if not args.apply:
            return
        require_backup("chroma", args.backup_max_age_hours)
        os.rename(live, aside)
        os.rename(work, live)
        state.data = {"moved": True, "old_store": str(aside), "at": datetime.now(timezone.utc).isoformat()}
        state.save()
        log(f"swapped; start the services again. Rollback (services stopped): "
            f"mv {live} {work} && mv {aside} {live}")
    # Vectors for this run's chunked abstracts are live now.
    guard_arango_writes(args)
    if not args.apply:
        return
    db = arango(args.arango_db)
    db.aql.execute(
        "FOR d IN documents FILTER d.repair_run == @rid AND d.embedding_status == 'chunked' "
        "UPDATE d WITH {embedding_status: 'embedded'} IN documents", bind_vars={"rid": rid})
    state.data["statuses_flipped"] = True
    state.save()
    log("documents of this run marked embedded")


def cmd_retire_arango(args) -> None:
    guard_arango_writes(args)
    if args.apply and not State(Path(args.state_dir), "swap").data.get("moved"):
        raise SystemExit("run swap first: the live vector store still serves these chunk ids")
    db = arango(args.arango_db)
    retire = State(Path(args.state_dir), "build-store").data.get("retire")
    if retire is None:
        raise SystemExit("run build-store first: it fixes the set of retired documents")
    state = State(Path(args.state_dir), "retire-duplicates-arango")
    done = set(state.data.get("done", []))
    todo = [d for d in retire if d not in done]
    n = next(iter(db.aql.execute(
        "RETURN LENGTH(FOR c IN chunks FILTER c.document_id IN @docs RETURN 1)", bind_vars={"docs": todo})))
    log(f"Arango chunks to delete: {n:,} from {len(todo)} duplicate-lineage documents")
    if not args.apply:
        return
    for i, doc_id in enumerate(todo, 1):
        db.aql.execute(REMOVE_STALE_AQL, bind_vars={"doc": doc_id, "keep": []})
        done.add(doc_id)
        if i % 50 == 0 or i == len(todo):
            state.data["done"] = sorted(done)
            state.save()
            log(f"{len(done)}/{len(retire)} documents' chunks removed")


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", nargs="?", default="plan", choices=[
        "plan", "rechunk-library", "chunk-abstracts", "build-store", "verify", "swap",
        "retire-duplicates-arango"])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--production", action="store_true", help="confirm writes to a production Arango database")
    ap.add_argument("--arango-db", default=settings.ARANGO_DB_NAME)
    ap.add_argument("--work-chroma", default=str(Path(settings.CHROMA_PERSIST_DIR).with_name("chromadb.repair-work")))
    ap.add_argument("--state-dir", default=str(Path(settings.CHROMA_PERSIST_DIR).with_name("repair-state")))
    ap.add_argument("--device", default=None, help="embedding device, e.g. cuda:0 or cpu")
    ap.add_argument("--batch-size", type=int, default=500, help="abstracts per chunk-abstracts batch")
    ap.add_argument("--build-batch", type=int, default=5000, help="chunks per build-store batch")
    ap.add_argument("--limit", type=int, default=0, help="stop after about this many items (0 = all)")
    ap.add_argument("--backup-max-age-hours", type=float, default=26.0)
    args = ap.parse_args()
    {
        "plan": cmd_plan,
        "rechunk-library": cmd_rechunk_library,
        "chunk-abstracts": cmd_chunk_abstracts,
        "build-store": cmd_build_store,
        "verify": cmd_verify,
        "swap": cmd_swap,
        "retire-duplicates-arango": cmd_retire_arango,
    }[args.phase](args)


if __name__ == "__main__":
    main()
