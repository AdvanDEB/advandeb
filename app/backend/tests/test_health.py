"""
/api/health and /health are public. When the database ping failed they put
``str(exception)`` in the response, which for a Mongo error can carry the
connection URI, hostnames and driver internals (F-024). The detail now goes to
the server log; the response says only that the database is unavailable.

Runs against the shared ``client`` fixture: no lifespan, no real database.
"""
import logging

import pytest

SECRET = "mongodb://admin:hunter2@10.0.0.7:27017 ServerSelectionTimeoutError"


class _FailingDb:
    async def command(self, name):
        raise RuntimeError(SECRET)


class _HealthyDb:
    async def command(self, name):
        return {"ok": 1}


@pytest.mark.parametrize("path", ["/api/health", "/health"])
def test_a_failed_ping_is_reported_without_its_detail(client, monkeypatch, caplog, path):
    from app.core import database
    monkeypatch.setattr(database, "get_database", lambda: _FailingDb())

    with caplog.at_level(logging.ERROR, logger="app.main"):
        r = client.get(path)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    assert "hunter2" not in r.text and "10.0.0.7" not in r.text and "Error" not in r.text
    # ...but the operator still gets it.
    assert any(SECRET in (rec.exc_text or "") or SECRET in str(rec.exc_info) for rec in caplog.records)


def test_a_healthy_ping(client, monkeypatch):
    from app.core import database
    monkeypatch.setattr(database, "get_database", lambda: _HealthyDb())
    body = client.get("/api/health").json()
    assert body["status"] == "healthy"
    assert body["database"] == "connected"
