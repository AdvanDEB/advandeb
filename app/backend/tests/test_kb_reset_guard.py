"""The KB reset truncates canonical ArangoDB collections: it must be hard to do.

A single admin click used to be enough. Now the database name has to be typed
back and a recent backup of that database has to exist.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from advandeb_kb.backup_guard import NoRecentBackupError
from app.api.routes.kb import database as route

ADMIN = {"id": "admin1", "roles": ["administrator"]}


@pytest.fixture
def fake_arango(monkeypatch):
    collection = MagicMock()
    collection.count.return_value = 42
    db = MagicMock()
    db.name = "advandeb_kb"
    db.has_collection.return_value = True
    db.collection.return_value = collection
    monkeypatch.setattr(route, "get_arango_db", lambda: SimpleNamespace(db=db))
    return collection


async def test_wrong_confirmation_is_refused(fake_arango, monkeypatch):
    monkeypatch.setattr(route, "require_recent_backup", lambda *a, **k: {"_path": "/b/run"})
    with pytest.raises(HTTPException) as exc:
        await route.reset_knowledge_base(route.ResetRequest(confirm="yes"), current_user=ADMIN)
    assert exc.value.status_code == 400
    fake_arango.truncate.assert_not_called()


async def test_missing_backup_is_refused(fake_arango, monkeypatch):
    def no_backup(*args, **kwargs):
        raise NoRecentBackupError("no successful backup of 'arango:advandeb_kb'")

    monkeypatch.setattr(route, "require_recent_backup", no_backup)
    with pytest.raises(HTTPException) as exc:
        await route.reset_knowledge_base(
            route.ResetRequest(confirm="advandeb_kb"), current_user=ADMIN)
    assert exc.value.status_code == 409
    fake_arango.truncate.assert_not_called()


async def test_confirmed_reset_with_backup_truncates(fake_arango, monkeypatch):
    seen = {}

    def recent(component, max_age_hours):
        seen["component"] = component
        return {"_path": "/b/20261028T031500Z-daily"}

    monkeypatch.setattr(route, "require_recent_backup", recent)
    result = await route.reset_knowledge_base(
        route.ResetRequest(confirm="advandeb_kb"), current_user=ADMIN)
    assert seen["component"] == "arango:advandeb_kb"
    assert result["restore_point"] == "/b/20261028T031500Z-daily"
    assert fake_arango.truncate.call_count == len(route._CLEARABLE_ARANGO)
