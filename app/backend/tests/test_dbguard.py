"""The guard that would have prevented the production data loss."""

import os

import pytest

from app.core.dbguard import (
    ProductionDatabaseError, assert_not_production, is_scratch,
    require_scratch_db,
)


def test_production_names_are_refused():
    for name in ("advandeb", "advandeb_kb", "deb_literature_review"):
        assert not is_scratch(name)
        with pytest.raises(ProductionDatabaseError):
            assert_not_production(name)


def test_scratch_names_pass():
    for name in ("advandeb_scratch", "advandeb_test", "test_elicitation",
                 "sandbox_db", "tmp_verify"):
        assert is_scratch(name)
        assert_not_production(name)          # does not raise


def test_unknown_name_fails_closed():
    """A database nobody classified is dangerous, not safe.

    Excluding known production names would let a typo through; requiring the
    scratch marker is what makes the default direction safe.
    """
    assert not is_scratch("some_new_database")
    with pytest.raises(ProductionDatabaseError):
        assert_not_production("some_new_database")


def test_empty_is_refused():
    assert not is_scratch("")
    with pytest.raises(ProductionDatabaseError):
        assert_not_production("")


def test_reproduces_the_actual_incident(monkeypatch):
    """The exact failure: setdefault against an already-set variable.

    `.env` exports MONGODB_DB_NAME=advandeb, so setdefault is a no-op and the
    target silently stays production. The guard catches what the default missed.
    """
    monkeypatch.setenv("MONGODB_DB_NAME", "advandeb")       # as .env leaves it
    os.environ.setdefault("MONGODB_DB_NAME", "advandeb_scratch")   # the no-op
    assert os.environ["MONGODB_DB_NAME"] == "advandeb"      # still production
    with pytest.raises(ProductionDatabaseError, match="setdefault"):
        require_scratch_db()


def test_require_scratch_db_returns_the_name_when_safe(monkeypatch):
    monkeypatch.setenv("MONGODB_DB_NAME", "advandeb_scratch")
    assert require_scratch_db() == "advandeb_scratch"


def test_unset_is_refused_rather_than_guessed(monkeypatch):
    monkeypatch.delenv("MONGODB_DB_NAME", raising=False)
    with pytest.raises(ProductionDatabaseError, match="not set"):
        require_scratch_db()
