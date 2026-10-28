#!/usr/bin/env python
"""Back up AdvanDEB's stores: MongoDB, ArangoDB and the ChromaDB vector store.

Production collections were dropped once (commit 0cd580c) with no dump, no
snapshot and no oplog to recover from. This job makes every store restorable
and records what it captured, so that irreversible operations can check for a
recent restore point first (``advandeb_kb.backup_guard``).

Profiles
    daily   MongoDB advandeb, advandeb_knowledge_builder_kb, deb_literature_review
            + ArangoDB (ARANGO_DB_NAME, default advandeb_kb)
    weekly  everything in daily
            + MongoDB deb_abstracts_reproduction (~60 GB)
            + the ChromaDB store (~17 GB)

Layout of one run, under $ADVANDEB_BACKUP_DIR (default ~/backups/advandeb)::

    20261028T031500Z-daily/
        mongo/<db>/<collection>.bson.gz            mongorestore --gzip layout
        mongo/<db>/<collection>.metadata.json.gz
        arango/<db>/                               arangodump output, compressed
        chroma/                                    sqlite online backup + segment dirs
        manifest.json                              written last; status per component

A run is written into ``<name>.partial`` and renamed when it ends, so an
interrupted run is never mistaken for a restore point. The manifest records a
status per component: a failed ArangoDB dump does not invalidate a good Mongo
dump taken in the same run.

Consistency: MongoDB here is a standalone server without an oplog, so a dump is
not a point-in-time snapshot of a database that is being written to. Counts per
collection are recorded so a restore can be checked against them.

Everything this script does against the stores is a read. Usage::

    python scripts/backup/advandeb_backup.py --profile daily
    python scripts/backup/advandeb_backup.py --profile weekly --keep 4
    python scripts/backup/advandeb_backup.py --profile daily --only mongo:advandeb
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import json
import logging
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
ENV_FILE = REPO / "app" / "backend" / ".env"
MANIFEST_NAME = "manifest.json"
PARTIAL_SUFFIX = ".partial"
FORMAT_VERSION = 1

APP_MONGO_DBS = ["advandeb", "advandeb_knowledge_builder_kb", "deb_literature_review"]
PROFILES: Dict[str, Dict[str, Any]] = {
    "daily": {"mongo": APP_MONGO_DBS, "arango": True, "chroma": False},
    "weekly": {"mongo": APP_MONGO_DBS + ["deb_abstracts_reproduction"], "arango": True, "chroma": True},
}
DEFAULT_KEEP = {"daily": 7, "weekly": 4}
STALE_PARTIAL_AGE = timedelta(days=2)

log = logging.getLogger("advandeb-backup")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: datetime) -> str:
    return ts.isoformat(timespec="seconds").replace("+00:00", "Z")


def backup_root() -> Path:
    configured = os.environ.get("ADVANDEB_BACKUP_DIR")
    return Path(configured) if configured else Path.home() / "backups" / "advandeb"


def load_env() -> Dict[str, str]:
    """Connection settings: app/backend/.env, overridden by the process env."""
    env: Dict[str, str] = {}
    if ENV_FILE.exists():
        from dotenv import dotenv_values

        env.update({k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None})
    env.update({k: v for k, v in os.environ.items()
                if k.startswith(("MONGODB_", "ARANGO_", "CHROMA_"))})
    return env


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# --------------------------------------------------------------------------- #
# MongoDB
# --------------------------------------------------------------------------- #

def _write_gz_json(path: Path, payload: Any) -> None:
    from bson import json_util

    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json_util.dumps(payload))


def dump_mongo_db(client, db_name: str, out_dir: Path) -> Dict[str, Any]:
    """Write every collection of ``db_name`` as gzipped BSON plus metadata.

    Documents are streamed as raw BSON (never decoded), which is both the
    fastest path and byte-identical to what mongodump writes.
    """
    from bson.codec_options import CodecOptions
    from bson.raw_bson import RawBSONDocument

    db = client[db_name]
    target = out_dir / db_name
    target.mkdir(parents=True, exist_ok=True)
    raw_options = CodecOptions(document_class=RawBSONDocument)
    collections: Dict[str, Any] = {}

    for info in db.list_collections():
        name = info["name"]
        if name.startswith("system."):
            continue
        ctype = info.get("type", "collection")
        meta: Dict[str, Any] = {
            "collectionName": name,
            "type": ctype,
            "options": info.get("options", {}),
            "indexes": [],
        }
        if ctype == "view":
            _write_gz_json(target / f"{name}.metadata.json.gz", meta)
            collections[name] = {"type": "view"}
            continue

        meta["indexes"] = list(db[name].list_indexes())
        n_docs = n_bytes = 0
        with gzip.open(target / f"{name}.bson.gz", "wb", compresslevel=6) as fh:
            for doc in db.get_collection(name, codec_options=raw_options).find({}, batch_size=2000):
                raw = doc.raw
                fh.write(raw)
                n_docs += 1
                n_bytes += len(raw)
        _write_gz_json(target / f"{name}.metadata.json.gz", meta)
        collections[name] = {"documents": n_docs, "bytes": n_bytes}

    return {
        "collections": collections,
        "documents": sum(c.get("documents", 0) for c in collections.values()),
    }


# --------------------------------------------------------------------------- #
# ArangoDB
# --------------------------------------------------------------------------- #

def arango_endpoint(url: str) -> str:
    """http://host:8529 -> tcp://host:8529 (the form arangodump expects)."""
    scheme, _, rest = url.partition("://")
    if not rest:
        scheme, rest = "http", url
    return ("ssl://" if scheme == "https" else "tcp://") + rest.rstrip("/")


def write_arango_client_config(env: Dict[str, str], db_name: str) -> str:
    """A 0600 config file for arangodump/arangorestore.

    The password goes in a file rather than on the command line, where any
    local user could read it from the process list.
    """
    fd, path = tempfile.mkstemp(prefix="arango-", suffix=".conf")
    with os.fdopen(fd, "w") as fh:
        fh.write(
            "[server]\n"
            f"endpoint = {arango_endpoint(env.get('ARANGO_URL', 'http://localhost:8529'))}\n"
            f"username = {env.get('ARANGO_USERNAME', 'root')}\n"
            f"password = {env.get('ARANGO_PASSWORD', '')}\n"
            f"database = {db_name}\n"
        )
    return path


def arango_counts(env: Dict[str, str], db_name: str) -> Dict[str, int]:
    from arango import ArangoClient

    db = ArangoClient(hosts=env.get("ARANGO_URL", "http://localhost:8529")).db(
        db_name, username=env.get("ARANGO_USERNAME", "root"),
        password=env.get("ARANGO_PASSWORD", ""))
    return {c["name"]: db.collection(c["name"]).count()
            for c in db.collections() if not c["system"]}


def dump_arango(env: Dict[str, str], db_name: str, out_dir: Path) -> Dict[str, Any]:
    counts = arango_counts(env, db_name)
    target = out_dir / db_name
    out_dir.mkdir(parents=True, exist_ok=True)     # arangodump won't create parents
    conf = write_arango_client_config(env, db_name)
    try:
        proc = subprocess.run(
            ["arangodump", "--configuration", conf,
             "--output-directory", str(target),
             "--compress-output", "true",
             "--include-system-collections", "false",
             "--threads", "4",
             "--overwrite", "false"],
            capture_output=True, text=True,
        )
    finally:
        os.unlink(conf)
    if proc.returncode != 0:
        output = (proc.stderr.strip() or proc.stdout.strip())[-2000:]
        raise RuntimeError(f"arangodump exited {proc.returncode}: {output}")
    return {"collections": counts, "documents": sum(counts.values())}


# --------------------------------------------------------------------------- #
# ChromaDB
# --------------------------------------------------------------------------- #

def backup_chroma(src: Path, out_dir: Path) -> Dict[str, Any]:
    """Copy the ChromaDB store.

    The sqlite file goes through sqlite's online backup API, which yields a
    consistent copy even while the retrieval agent has it open. The HNSW
    segment directories are copied as files; they only change while vectors
    are being written, which nothing does routinely. For a strictly consistent
    pair, stop ingestion before a weekly run.
    """
    db_src = src / "chroma.sqlite3"
    if not db_src.is_file():
        raise FileNotFoundError(f"no chroma.sqlite3 under {src}")
    out_dir.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(f"file:{db_src}?mode=ro", uri=True)
    dest = sqlite3.connect(out_dir / "chroma.sqlite3")
    try:
        source.backup(dest)
        embeddings = dest.execute("SELECT count(*) FROM embeddings").fetchone()[0]
    finally:
        dest.close()
        source.close()

    for entry in src.iterdir():
        if entry.name.startswith("chroma.sqlite3"):    # the db and its -wal/-shm
            continue
        if entry.is_dir():
            shutil.copytree(entry, out_dir / entry.name)
        else:
            shutil.copy2(entry, out_dir / entry.name)
    return {"embeddings": embeddings, "source": str(src)}


# --------------------------------------------------------------------------- #
# Retention
# --------------------------------------------------------------------------- #

def read_manifest(run: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads((run / MANIFEST_NAME).read_text())
    except (OSError, ValueError):
        return None


def prune(root: Path, profile: str, keep: int, now: Optional[datetime] = None) -> List[Path]:
    """Delete old runs of ``profile``, never touching the newest ``keep`` good runs.

    A run is good when every component succeeded. Nothing is deleted while
    there are ``keep`` or fewer good runs, so a streak of failures can never
    prune away the last restore points. Abandoned ``.partial`` directories
    older than two days are removed as well.
    """
    now = now or utcnow()
    removed: List[Path] = []
    runs = sorted(d for d in root.iterdir()
                  if d.is_dir() and d.name.endswith(f"-{profile}") and (d / MANIFEST_NAME).is_file())
    good = [d for d in runs if (read_manifest(d) or {}).get("status") == "ok"]
    if len(good) > keep:
        oldest_kept = good[-keep]
        for run in runs:
            if run.name < oldest_kept.name:
                shutil.rmtree(run)
                removed.append(run)

    for partial in root.glob(f"*-{profile}{PARTIAL_SUFFIX}"):
        age = now - datetime.fromtimestamp(partial.stat().st_mtime, timezone.utc)
        if partial.is_dir() and age > STALE_PARTIAL_AGE:
            shutil.rmtree(partial)
            removed.append(partial)
    return removed


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #

def git_commit() -> Optional[str]:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def plan_components(profile: str, env: Dict[str, str]) -> List[str]:
    spec = PROFILES[profile]
    components = [f"mongo:{db}" for db in spec["mongo"]]
    if spec["arango"]:
        components.append(f"arango:{env.get('ARANGO_DB_NAME', 'advandeb_kb')}")
    if spec["chroma"]:
        components.append("chroma")
    return components


def run_backup(profile: str, root: Path, only: Optional[List[str]] = None) -> Dict[str, Any]:
    env = load_env()
    components = plan_components(profile, env)
    if only:
        unknown = sorted(set(only) - set(components))
        if unknown:
            raise SystemExit(f"--only names components not in the {profile} profile: {unknown}")
        components = [c for c in components if c in only]

    started = utcnow()
    name = f"{started.strftime('%Y%m%dT%H%M%SZ')}-{profile}"
    work = root / f"{name}{PARTIAL_SUFFIX}"
    work.mkdir(parents=True)
    manifest: Dict[str, Any] = {
        "format": FORMAT_VERSION,
        "profile": profile,
        "host": socket.gethostname(),
        "git_commit": git_commit(),
        "started_at": iso(started),
        "components": {},
    }

    mongo_client = None
    for component in components:
        kind, _, target = component.partition(":")
        t0 = time.monotonic()
        log.info("backing up %s", component)
        try:
            if kind == "mongo":
                if mongo_client is None:
                    from pymongo import MongoClient

                    mongo_client = MongoClient(env.get("MONGODB_URI", "mongodb://localhost:27017"),
                                               serverSelectionTimeoutMS=10000)
                if target not in mongo_client.list_database_names():
                    raise RuntimeError(f"database {target!r} does not exist")
                result = dump_mongo_db(mongo_client, target, work / "mongo")
            elif kind == "arango":
                result = dump_arango(env, target, work / "arango")
            else:
                chroma_dir = Path(env.get("CHROMA_PERSIST_DIR") or REPO / "data" / "chromadb")
                result = backup_chroma(chroma_dir, work / "chroma")
            entry = {"status": "ok", **result}
        except Exception as exc:          # one store failing must not stop the others
            log.exception("%s failed", component)
            entry = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        entry["seconds"] = round(time.monotonic() - t0, 1)
        manifest["components"][component] = entry
        log.info("%s: %s in %.0f s", component, entry["status"], entry["seconds"])

    if mongo_client is not None:
        mongo_client.close()

    finished = utcnow()
    failed = [c for c, e in manifest["components"].items() if e["status"] != "ok"]
    manifest["finished_at"] = iso(finished)
    manifest["status"] = "failed" if failed else "ok"
    manifest["failed_components"] = failed
    manifest["size_bytes"] = dir_size(work)
    (work / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    final = root / name
    work.rename(final)
    manifest["_path"] = str(final)
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--profile", choices=sorted(PROFILES), default="daily")
    parser.add_argument("--keep", type=int, default=None,
                        help="good runs of this profile to keep (default: daily 7, weekly 4)")
    parser.add_argument("--only", nargs="+", metavar="COMPONENT",
                        help="back up only these components, e.g. mongo:advandeb arango:advandeb_kb")
    parser.add_argument("--no-prune", action="store_true", help="skip retention cleanup")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = backup_root()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)            # dumps contain user records and encrypted keys

    with open(root / ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.error("another backup is running (lock %s)", root / ".lock")
            return 2

        manifest = run_backup(args.profile, root, args.only)
        log.info("run %s: %s, %.2f GB", manifest["_path"], manifest["status"],
                 manifest["size_bytes"] / 1e9)

        if not args.no_prune and not args.only:
            keep = args.keep if args.keep is not None else DEFAULT_KEEP[args.profile]
            for removed in prune(root, args.profile, keep):
                log.info("pruned %s", removed)

    return 0 if manifest["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
