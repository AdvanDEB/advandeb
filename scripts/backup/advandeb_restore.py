#!/usr/bin/env python
"""Restore, or rehearse restoring, a backup made by advandeb_backup.py.

A backup nobody has restored is a hope, not a backup. ``verify`` is the drill:
it restores every component of a run into throwaway databases, compares each
collection's count with the manifest, and drops the throwaway databases again.
Run it after the first backup and periodically after that.

Subcommands::

    list                          runs, newest first, with status and age
    verify [--run latest|PATH]    restore into *_restore_scratch_* DBs, compare, drop
    mongo  --db NAME [--run ...] [--target NAME] [--replace] [--confirm NAME]
    arango [--db NAME] [--run ...] [--target NAME] [--overwrite] [--confirm NAME]

Restores default to a new scratch database next to production, never onto it.
Writing into a database that is not scratch needs ``--confirm <that name>``;
existing non-empty Mongo collections are skipped unless ``--replace`` is given
as well. ChromaDB is restored by copying the run's ``chroma/`` directory back
while the retrieval agent is stopped (see scripts/backup/README.md).
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "app" / "backend"))

import advandeb_backup as bk  # noqa: E402
from app.core.dbguard import assert_not_production, is_scratch  # noqa: E402


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #

def list_runs(root: Path) -> List[Path]:
    return sorted((d for d in root.iterdir()
                   if d.is_dir() and (d / bk.MANIFEST_NAME).is_file()),
                  key=lambda d: d.name, reverse=True)


def resolve_run(root: Path, run: str) -> Path:
    if run == "latest":
        runs = list_runs(root) if root.is_dir() else []
        if not runs:
            raise SystemExit(f"no backup runs under {root}")
        return runs[0]
    path = Path(run)
    path = path if path.is_absolute() else root / path
    if not (path / bk.MANIFEST_NAME).is_file():
        raise SystemExit(f"{path} is not a backup run (no {bk.MANIFEST_NAME})")
    return path


def require_confirmation(target: str, confirm: Optional[str]) -> None:
    """Writing anywhere but a scratch database needs the name typed back."""
    if is_scratch(target):
        return
    if confirm != target:
        raise SystemExit(
            f"refusing to restore into {target!r}: it is not a scratch database. "
            f"Pass --confirm {target} if that is really the target."
        )


# --------------------------------------------------------------------------- #
# MongoDB
# --------------------------------------------------------------------------- #

def restore_mongo_db(client, run: Path, db_name: str, target: str,
                     replace: bool = False) -> Dict[str, Any]:
    from bson import decode_file_iter, json_util
    from bson.codec_options import CodecOptions
    from bson.raw_bson import RawBSONDocument

    src = run / "mongo" / db_name
    if not src.is_dir():
        raise SystemExit(f"run {run.name} has no MongoDB dump of {db_name!r}")
    tdb = client[target]
    raw = CodecOptions(document_class=RawBSONDocument)
    report: Dict[str, Any] = {}

    for meta_path in sorted(src.glob("*.metadata.json.gz")):
        name = meta_path.name[: -len(".metadata.json.gz")]
        with gzip.open(meta_path, "rt", encoding="utf-8") as fh:
            meta = json_util.loads(fh.read())
        options = dict(meta.get("options") or {})
        exists = name in tdb.list_collection_names()

        if meta.get("type") == "view":
            if not exists:
                tdb.command({"create": name, **options})
            report[name] = "view"
            continue
        if exists and tdb[name].estimated_document_count() > 0:
            if not replace:
                report[name] = "skipped: target collection is not empty"
                continue
            tdb[name].drop()
            exists = False
        if not exists:
            tdb.create_collection(name, **options)

        inserted, batch = 0, []
        with gzip.open(src / f"{name}.bson.gz", "rb") as fh:
            for doc in decode_file_iter(fh, codec_options=raw):
                batch.append(doc)
                if len(batch) >= 1000:
                    inserted += len(tdb[name].insert_many(batch, ordered=False).inserted_ids)
                    batch = []
        if batch:
            inserted += len(tdb[name].insert_many(batch, ordered=False).inserted_ids)

        for index in meta.get("indexes") or []:
            if index.get("name") == "_id_":
                continue
            keys = list(index["key"].items())
            kwargs = {k: v for k, v in index.items() if k not in ("v", "key", "ns")}
            tdb[name].create_index(keys, **kwargs)
        report[name] = inserted
    return report


# --------------------------------------------------------------------------- #
# ArangoDB
# --------------------------------------------------------------------------- #

def restore_arango(env: Dict[str, str], run: Path, db_name: str, target: str,
                   create_database: bool, overwrite: bool) -> None:
    src = run / "arango" / db_name
    if not src.is_dir():
        raise SystemExit(f"run {run.name} has no ArangoDB dump of {db_name!r}")
    conf = bk.write_arango_client_config(env, target)
    try:
        proc = subprocess.run(
            ["arangorestore", "--configuration", conf,
             "--input-directory", str(src),
             "--create-database", "true" if create_database else "false",
             "--overwrite", "true" if overwrite else "false",
             "--threads", "4"],
            capture_output=True, text=True,
        )
    finally:
        Path(conf).unlink()
    if proc.returncode != 0:
        output = (proc.stderr.strip() or proc.stdout.strip())[-2000:]
        raise RuntimeError(f"arangorestore exited {proc.returncode}: {output}")


def drop_arango_scratch(env: Dict[str, str], name: str) -> None:
    from arango import ArangoClient

    assert_not_production(name, "dropping a restore-drill database")
    ArangoClient(hosts=env.get("ARANGO_URL", "http://localhost:8529")).db(
        "_system", username=env.get("ARANGO_USERNAME", "root"),
        password=env.get("ARANGO_PASSWORD", "")).delete_database(name, ignore_missing=True)


# --------------------------------------------------------------------------- #
# Drill
# --------------------------------------------------------------------------- #

def compare(expected: Dict[str, int], restored: Dict[str, int]) -> List[str]:
    problems = []
    for name in sorted(set(expected) | set(restored)):
        want, got = expected.get(name), restored.get(name)
        if want != got:
            problems.append(f"{name}: manifest {want}, restored {got}")
    return problems


def verify(run: Path, keep_scratch: bool, only: Optional[List[str]]) -> int:
    from pymongo import MongoClient

    env = bk.load_env()
    manifest = json.loads((run / bk.MANIFEST_NAME).read_text())
    stamp = run.name.split("-")[0].lower()
    client = MongoClient(env.get("MONGODB_URI", "mongodb://localhost:27017"))
    failures = 0

    for component, entry in manifest["components"].items():
        if only and component not in only:
            continue
        if entry.get("status") != "ok":
            print(f"SKIP  {component}: not backed up successfully in this run")
            continue
        kind, _, name = component.partition(":")
        if kind == "mongo":
            target = f"{name}_restore_scratch_{stamp}"
            assert_not_production(target, "restore drill")
            client.drop_database(target)
            restore_mongo_db(client, run, name, target)
            restored = {c: client[target][c].count_documents({})
                        for c in client[target].list_collection_names()
                        if not c.startswith("system.")}
            expected = {c: v["documents"] for c, v in entry["collections"].items()
                        if "documents" in v}
            restored = {c: n for c, n in restored.items() if c in expected or n}
            problems = compare(expected, restored)
            if not keep_scratch:
                client.drop_database(target)
        elif kind == "arango":
            target = f"{name}_restore_scratch_{stamp}"
            drop_arango_scratch(env, target)
            restore_arango(env, run, name, target, create_database=True, overwrite=True)
            problems = compare(entry["collections"], bk.arango_counts(env, target))
            if not keep_scratch:
                drop_arango_scratch(env, target)
        elif kind == "chroma":
            con = sqlite3.connect(f"file:{run / 'chroma' / 'chroma.sqlite3'}?mode=ro", uri=True)
            try:
                got = con.execute("SELECT count(*) FROM embeddings").fetchone()[0]
            finally:
                con.close()
            problems = compare({"embeddings": entry["embeddings"]}, {"embeddings": got})
        else:
            problems = [f"unknown component kind {kind!r}"]

        status = "OK  " if not problems else "FAIL"
        total = entry.get("documents", entry.get("embeddings"))
        print(f"{status}  {component} ({total} records)")
        for problem in problems:
            print(f"        {problem}")
        failures += bool(problems)

    client.close()
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list backup runs")

    p_verify = sub.add_parser("verify", help="restore into scratch DBs and compare counts")
    p_verify.add_argument("--run", default="latest")
    p_verify.add_argument("--only", nargs="+", metavar="COMPONENT")
    p_verify.add_argument("--keep-scratch", action="store_true",
                          help="leave the scratch databases in place for inspection")

    p_mongo = sub.add_parser("mongo", help="restore one MongoDB database")
    p_mongo.add_argument("--db", required=True, help="database name as backed up")
    p_mongo.add_argument("--run", default="latest")
    p_mongo.add_argument("--target", help="target database (default: <db>_restore_scratch_<stamp>)")
    p_mongo.add_argument("--replace", action="store_true",
                         help="drop and restore target collections that are not empty")
    p_mongo.add_argument("--confirm", help="the target name, required for non-scratch targets")

    p_arango = sub.add_parser("arango", help="restore the ArangoDB database")
    p_arango.add_argument("--db", default=None, help="database name as backed up")
    p_arango.add_argument("--run", default="latest")
    p_arango.add_argument("--target", help="target database (default: <db>_restore_scratch_<stamp>)")
    p_arango.add_argument("--overwrite", action="store_true",
                          help="overwrite collections that exist in the target")
    p_arango.add_argument("--confirm", help="the target name, required for non-scratch targets")

    args = parser.parse_args(argv)
    root = bk.backup_root()

    if args.command == "list":
        for run in list_runs(root) if root.is_dir() else []:
            m = bk.read_manifest(run) or {}
            comps = ", ".join(f"{c}={e.get('status')}" for c, e in (m.get("components") or {}).items())
            print(f"{run.name:28s} {m.get('status', '?'):7s} {m.get('size_bytes', 0) / 1e9:7.2f} GB  {comps}")
        return 0

    run = resolve_run(root, args.run)
    stamp = run.name.split("-")[0].lower()

    if args.command == "verify":
        return verify(run, args.keep_scratch, args.only)

    if args.command == "mongo":
        from pymongo import MongoClient

        target = args.target or f"{args.db}_restore_scratch_{stamp}"
        require_confirmation(target, args.confirm)
        env = bk.load_env()
        client = MongoClient(env.get("MONGODB_URI", "mongodb://localhost:27017"))
        report = restore_mongo_db(client, run, args.db, target, replace=args.replace)
        client.close()
        for name, outcome in report.items():
            print(f"{target}.{name}: {outcome}")
        return 0

    env = bk.load_env()
    db_name = args.db or env.get("ARANGO_DB_NAME", "advandeb_kb")
    target = args.target or f"{db_name}_restore_scratch_{stamp}"
    require_confirmation(target, args.confirm)
    restore_arango(env, run, db_name, target, create_database=is_scratch(target),
                   overwrite=args.overwrite)
    print(f"restored {db_name} from {run.name} into {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
