"""Configuration resolution shared by the app and the KB (advandeb_kb.config.env)."""
from __future__ import annotations

import importlib

import pytest

from advandeb_kb.config import env


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setenv("ADVANDEB_ENV_FILE", str(path))
    env._file_values.cache_clear()
    yield path
    env._file_values.cache_clear()


def test_file_is_used_when_env_unset(env_file, monkeypatch):
    env_file.write_text("ARANGO_PASSWORD=from-file\n")
    monkeypatch.delenv("ARANGO_PASSWORD", raising=False)
    assert env.getenv("ARANGO_PASSWORD", "") == "from-file"


def test_process_env_beats_file(env_file, monkeypatch):
    env_file.write_text("ARANGO_PASSWORD=from-file\n")
    monkeypatch.setenv("ARANGO_PASSWORD", "from-env")
    assert env.getenv("ARANGO_PASSWORD", "") == "from-env"


def test_alias_in_env_beats_canonical_in_file(env_file, monkeypatch):
    """An explicit `MONGODB_URL=` override must not be shadowed by the file's MONGODB_URI."""
    env_file.write_text("MONGODB_URI=mongodb://file-host\n")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGODB_URL", "mongodb://env-host")
    assert env.getenv("MONGODB_URI", "d", aliases=("MONGODB_URL",)) == "mongodb://env-host"


def test_alias_in_file(env_file, monkeypatch):
    env_file.write_text("DATABASE_NAME=legacy_name\n")
    monkeypatch.delenv("KB_DB_NAME", raising=False)
    monkeypatch.delenv("DATABASE_NAME", raising=False)
    assert env.getenv("KB_DB_NAME", "d", aliases=("DATABASE_NAME",)) == "legacy_name"


def test_empty_setting_disables_file(monkeypatch, tmp_path):
    monkeypatch.setenv("ADVANDEB_ENV_FILE", "")
    assert env.env_file_path() is None
    assert env.getenv("SOMETHING_ONLY_IN_A_FILE", "default") == "default"


def test_file_values_are_not_exported(env_file, monkeypatch):
    import os

    env_file.write_text("SECRET_ONLY_IN_FILE=s3cret\n")
    monkeypatch.delenv("SECRET_ONLY_IN_FILE", raising=False)
    assert env.getenv("SECRET_ONLY_IN_FILE") == "s3cret"
    assert "SECRET_ONLY_IN_FILE" not in os.environ


def test_bool_and_int(env_file, monkeypatch):
    env_file.write_text("FLAG_A=False\nFLAG_B=1\nNUM=42\n")
    for name in ("FLAG_A", "FLAG_B", "NUM"):
        monkeypatch.delenv(name, raising=False)
    assert env.getenv_bool("FLAG_A", True) is False
    assert env.getenv_bool("FLAG_B", False) is True
    assert env.getenv_int("NUM", 0) == 42


def test_kb_settings_use_canonical_names_with_aliases(env_file, monkeypatch):
    env_file.write_text(
        "MONGODB_URI=mongodb://canonical\n"
        "KB_DB_NAME=kb_from_file\n"
        "MONGODB_DB_NAME=app_db_from_file\n"
    )
    for name in ("MONGODB_URI", "MONGODB_URL", "KB_DB_NAME", "DATABASE_NAME",
                 "CHAT_STORE_DB_NAME", "MONGODB_DB_NAME"):
        monkeypatch.delenv(name, raising=False)
    import advandeb_kb.config.settings as settings_module

    s = importlib.reload(settings_module).settings
    try:
        assert s.MONGODB_URI == s.MONGODB_URL == "mongodb://canonical"
        assert s.KB_DB_NAME == s.DATABASE_NAME == "kb_from_file"
        # The chat store is the app database unless set separately.
        assert s.CHAT_STORE_DB_NAME == "app_db_from_file"
    finally:
        monkeypatch.setenv("ADVANDEB_ENV_FILE", "")
        env._file_values.cache_clear()
        importlib.reload(settings_module)
