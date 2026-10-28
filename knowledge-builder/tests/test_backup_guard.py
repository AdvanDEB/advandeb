"""require_recent_backup: the check every irreversible operation leans on."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from advandeb_kb.backup_guard import (
    NoRecentBackupError, backup_age_hours, latest_backup, require_recent_backup,
)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
ARANGO = "arango:advandeb_kb"


def make_run(root, name, finished, components, status="ok"):
    run = root / name
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({
        "status": status,
        "finished_at": finished.isoformat().replace("+00:00", "Z"),
        "components": components,
    }))
    return run


def test_no_backup_dir_is_refused(tmp_path):
    with pytest.raises(NoRecentBackupError, match="no successful backup"):
        require_recent_backup(ARANGO, root=tmp_path / "missing", now=NOW)


def test_recent_successful_backup_passes(tmp_path):
    make_run(tmp_path, "20261028T030000Z-daily", NOW - timedelta(hours=9),
             {ARANGO: {"status": "ok"}})
    manifest = require_recent_backup(ARANGO, max_age_hours=26, root=tmp_path, now=NOW)
    assert manifest["_path"].endswith("20261028T030000Z-daily")


def test_stale_backup_is_refused(tmp_path):
    make_run(tmp_path, "20261025T030000Z-daily", NOW - timedelta(hours=81),
             {ARANGO: {"status": "ok"}})
    with pytest.raises(NoRecentBackupError, match="81.0 h old"):
        require_recent_backup(ARANGO, max_age_hours=26, root=tmp_path, now=NOW)


def test_failed_component_does_not_count(tmp_path):
    """A run whose ArangoDB dump failed is no restore point for ArangoDB."""
    make_run(tmp_path, "20261028T030000Z-daily", NOW - timedelta(hours=1),
             {ARANGO: {"status": "failed"}, "mongo:advandeb": {"status": "ok"}},
             status="failed")
    with pytest.raises(NoRecentBackupError):
        require_recent_backup(ARANGO, root=tmp_path, now=NOW)
    # ...but the Mongo dump from the same run is a valid restore point.
    assert latest_backup("mongo:advandeb", tmp_path) is not None


def test_unfinished_partial_run_is_ignored(tmp_path):
    run = make_run(tmp_path, "20261028T030000Z-daily", NOW - timedelta(hours=1),
                   {ARANGO: {"status": "ok"}})
    run.rename(tmp_path / "20261028T030000Z-daily.partial")
    assert latest_backup(ARANGO, tmp_path) is None


def test_newest_successful_run_wins(tmp_path):
    make_run(tmp_path, "20261026T030000Z-daily", NOW - timedelta(hours=57),
             {ARANGO: {"status": "ok"}})
    make_run(tmp_path, "20261028T030000Z-daily", NOW - timedelta(hours=9),
             {ARANGO: {"status": "ok"}})
    manifest = latest_backup(ARANGO, tmp_path)
    assert manifest["_path"].endswith("20261028T030000Z-daily")
    assert backup_age_hours(manifest, NOW) == pytest.approx(9)


def test_unreadable_manifest_is_skipped(tmp_path):
    bad = tmp_path / "20261028T030000Z-daily"
    bad.mkdir()
    (bad / "manifest.json").write_text("{not json")
    assert latest_backup(ARANGO, tmp_path) is None
