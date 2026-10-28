"""Retention and endpoint helpers of scripts/backup/advandeb_backup.py.

Retention is the part of a backup job that deletes things, so its one promise
is tested directly: it never removes the newest good restore points, however
many runs fail in a row.
"""

import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup" / "advandeb_backup.py"
spec = importlib.util.spec_from_file_location("advandeb_backup", SCRIPT)
bk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bk)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def make_run(root, day, status="ok", profile="daily"):
    run = root / f"202610{day:02d}T031500Z-{profile}"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"status": status}))
    return run


def names(root):
    return sorted(p.name for p in root.iterdir())


def test_keeps_newest_good_runs_and_drops_older(tmp_path):
    for day in range(1, 11):
        make_run(tmp_path, day)
    removed = bk.prune(tmp_path, "daily", keep=7, now=NOW)
    assert len(removed) == 3
    assert names(tmp_path)[0].startswith("20261004")


def test_failures_never_prune_the_last_good_runs(tmp_path):
    for day in (1, 2):
        make_run(tmp_path, day, "ok")
    for day in range(3, 20):
        make_run(tmp_path, day, "failed")
    assert bk.prune(tmp_path, "daily", keep=7, now=NOW) == []
    assert len(names(tmp_path)) == 19


def test_failed_runs_older_than_kept_window_are_removed(tmp_path):
    make_run(tmp_path, 1, "failed")
    for day in range(2, 10):
        make_run(tmp_path, day, "ok")
    bk.prune(tmp_path, "daily", keep=7, now=NOW)
    assert names(tmp_path)[0].startswith("20261003")


def test_other_profiles_are_untouched(tmp_path):
    for day in range(1, 10):
        make_run(tmp_path, day)
    weekly = make_run(tmp_path, 1, profile="weekly")
    bk.prune(tmp_path, "daily", keep=2, now=NOW)
    assert weekly.exists()


def test_stale_partial_runs_are_removed(tmp_path):
    stale = tmp_path / "20261020T031500Z-daily.partial"
    fresh = tmp_path / "20261028T031500Z-daily.partial"
    stale.mkdir()
    fresh.mkdir()
    old = (NOW - timedelta(days=3)).timestamp()
    os.utime(stale, (old, old))
    recent = (NOW - timedelta(hours=1)).timestamp()
    os.utime(fresh, (recent, recent))
    bk.prune(tmp_path, "daily", keep=7, now=NOW)
    assert not stale.exists() and fresh.exists()


def test_arango_endpoint_translation():
    assert bk.arango_endpoint("http://localhost:8529") == "tcp://localhost:8529"
    assert bk.arango_endpoint("https://db.example:8530/") == "ssl://db.example:8530"
    assert bk.arango_endpoint("localhost:8529") == "tcp://localhost:8529"


def test_arango_client_config_is_private(tmp_path, monkeypatch):
    monkeypatch.setattr(bk.tempfile, "tempdir", str(tmp_path))
    path = bk.write_arango_client_config({"ARANGO_PASSWORD": "pw"}, "advandeb_kb")
    try:
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"
        assert "database = advandeb_kb" in Path(path).read_text()
    finally:
        os.unlink(path)
