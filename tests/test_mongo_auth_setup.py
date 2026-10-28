"""scripts/mongo_auth_setup.py — password files and the .env URI (no MongoDB needed)."""
from __future__ import annotations

import importlib.util
import stat
from pathlib import Path
from urllib.parse import unquote_plus

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "mongo_auth_setup.py"


@pytest.fixture
def mas(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("mongo_auth_setup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SECRETS_DIR", tmp_path / "secrets")
    return module


def test_uri_escapes_credentials(mas):
    uri = mas.uri_for("advandeb_app", "p@ss:w/rd")
    assert uri.startswith("mongodb://advandeb_app:") and uri.endswith("@127.0.0.1:27017/?authSource=admin")
    userinfo = uri.split("://", 1)[1].rsplit("@", 1)[0]
    assert unquote_plus(userinfo.split(":", 1)[1]) == "p@ss:w/rd"


def test_password_files_are_private_and_reused(mas):
    first = mas.ensure_password("advandeb_app", create=True)
    path = mas.password_file("advandeb_app")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert mas.ensure_password("advandeb_app", create=True) == first   # idempotent
    assert mas.ensure_password("nobody", create=False) is None


def test_write_env_sets_uri_and_keeps_the_rest(mas, tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("MONGODB_URI=mongodb://localhost:27017\nMONGODB_DB_NAME=advandeb\n")
    monkeypatch.setenv("ADVANDEB_ENV_FILE", str(env_file))
    password = mas.ensure_password("advandeb_app", create=True)

    mas.write_env()
    text = env_file.read_text()
    assert "MONGODB_DB_NAME=advandeb\n" in text
    assert text.count("MONGODB_URI=") == 1
    assert "@127.0.0.1:27017/?authSource=admin" in text
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert password not in capsys.readouterr().out


def test_app_user_cannot_reach_cadapti(mas):
    dbs = {r["db"] for r in mas.USERS["advandeb_app"]}
    assert "cadapti" not in dbs and "admin" not in dbs
