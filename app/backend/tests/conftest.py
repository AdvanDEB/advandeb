"""Shared fixtures.

`scratch_db` is the only fixture here that touches a real MongoDB, and it is
opt-in: a test gets a database only by asking for it.

It refuses two things, both failing closed:

* **a production database name** — this machine is production, and a
  verification script has already dropped two production collections once
  (see app/core/dbguard.py);
* **a server that holds production data at all**, whatever the database is
  called. Learned the hard way: the elicitation suite, run against scratch
  databases on the production server, put that server (the MongoDB 6.0
  container on :27017) into a restart loop — the churn of creating and
  dropping a database per test is not something to aim at the server
  everything else depends on. A guarded *name* is not enough; the tests get a
  server of their own.

Start a throwaway server (any mongod works; this is the one used here):

    conda create -n advandeb-mongotest -c conda-forge mongodb=6.0.16
    mkdir -p /tmp/advandeb-mongotest
    conda run -n advandeb-mongotest mongod --dbpath /tmp/advandeb-mongotest \
        --port 27118 --bind_ip 127.0.0.1 --fork --logpath /tmp/advandeb-mongotest.log

and run the database-backed tests against it, naming both explicitly:

    TEST_MONGODB_URI=mongodb://127.0.0.1:27118 \
    MONGODB_URI=mongodb://127.0.0.1:27118 \
    MONGODB_DB_NAME=advandeb_test_elicitation \
    JWT_SECRET_KEY=test \
    conda run -n advandeb python -m pytest tests/test_elicitation_*.py

Without TEST_MONGODB_URI and MONGODB_DB_NAME those tests skip.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def scratch_db(monkeypatch):
    """A fresh, guarded, per-process scratch database, dropped afterwards."""
    from app.core import dbguard

    uri = os.environ.get("TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TEST_MONGODB_URI not set — point it at a throwaway "
                    "mongod (see tests/conftest.py), never the production one")
    if not os.environ.get("MONGODB_DB_NAME"):
        pytest.skip("MONGODB_DB_NAME not set — set it to a scratch database "
                    "(e.g. advandeb_test_elicitation) to run database tests")
    # Reads the environment as it actually is and raises on a production name.
    # The `.env` file is deliberately not consulted: settings loads it, the
    # environment does not, so a shell that never named a database skips above
    # instead of inheriting `advandeb` from the file.
    base = dbguard.require_scratch_db()
    name = f"{base}_{os.getpid()}"
    dbguard.assert_not_production(name, "test database setup")

    from motor.motor_asyncio import AsyncIOMotorClient

    from app.core import database
    from app.core.config import settings

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=2000)
    try:
        held = set(await client.list_database_names())
    except Exception as exc:  # pragma: no cover - environment dependent
        client.close()
        pytest.skip(f"test MongoDB unreachable at {uri}: {exc}")
    production_here = sorted(held & dbguard.PRODUCTION_DATABASES)
    if production_here:
        client.close()
        raise dbguard.ProductionDatabaseError(
            f"refusing to run tests against {uri}: it holds production "
            f"databases {production_here}. Tests get a throwaway server of "
            f"their own (see tests/conftest.py).")

    monkeypatch.setattr(settings, "MONGODB_DB_NAME", name)
    monkeypatch.setattr(database.db, "client", client)
    db = database.get_database()
    # The service resolves its database through the same call; check it is
    # the scratch one before anything is dropped, not after.
    dbguard.assert_not_production(db.name, "test database drop")
    await client.drop_database(db.name)
    try:
        yield db
    finally:
        dbguard.assert_not_production(db.name, "test database drop")
        await client.drop_database(db.name)
        client.close()
