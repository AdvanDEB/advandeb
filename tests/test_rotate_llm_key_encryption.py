"""scripts/rotate_llm_key_encryption.py — env staging and key classification."""
from __future__ import annotations

import importlib.util
import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rotate_llm_key_encryption.py"


@pytest.fixture
def rot(monkeypatch):
    for name in ("LLM_KEY_ENCRYPTION_KEY", "LLM_KEY_ENCRYPTION_KEY_PREVIOUS"):
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("rotate_llm_key_encryption", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage_then_finish_env(rot, tmp_path, monkeypatch, capsys):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_NAME=x\n"
        "# BYOK Fernet key — derived from the passphrase 'hunter2'\n"
        f"LLM_KEY_ENCRYPTION_KEY={old}\n"
        "DEFAULT_CHAT_RPM=40\n"
    )
    env_file.chmod(0o664)
    key_file = tmp_path / "new.key"
    key_file.write_text(new + "\n")
    monkeypatch.setenv("ADVANDEB_ENV_FILE", str(env_file))

    rot.stage_env(key_file)
    staged = env_file.read_text()
    assert f"LLM_KEY_ENCRYPTION_KEY={new}\n" in staged
    assert f"LLM_KEY_ENCRYPTION_KEY_PREVIOUS={old}\n" in staged
    assert "passphrase" not in staged and "hunter2" not in staged
    assert "APP_NAME=x" in staged and "DEFAULT_CHAT_RPM=40" in staged
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    backups = list(tmp_path.glob(".env.bak-*"))
    assert len(backups) == 1 and stat.S_IMODE(backups[0].stat().st_mode) == 0o600

    out = capsys.readouterr().out
    assert old not in out and new not in out          # never prints key material

    rot.finish_env()
    finished = env_file.read_text()
    assert "LLM_KEY_ENCRYPTION_KEY_PREVIOUS" not in finished
    assert f"LLM_KEY_ENCRYPTION_KEY={new}\n" in finished


def test_stage_refuses_same_key(rot, tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    env_file = tmp_path / ".env"
    env_file.write_text(f"LLM_KEY_ENCRYPTION_KEY={key}\n")
    key_file = tmp_path / "k"
    key_file.write_text(key)
    monkeypatch.setenv("ADVANDEB_ENV_FILE", str(env_file))
    with pytest.raises(SystemExit):
        rot.stage_env(key_file)


def test_classify(rot):
    primary, previous, stranger = (Fernet(Fernet.generate_key()) for _ in range(3))
    assert rot.classify(primary.encrypt(b"k").decode(), primary, [previous]) == "primary"
    assert rot.classify(previous.encrypt(b"k").decode(), primary, [previous]) == "previous"
    assert rot.classify(stranger.encrypt(b"k").decode(), primary, [previous]) == "undecryptable"


def test_generate_key_file_is_private(rot, tmp_path, monkeypatch, capsys):
    target = tmp_path / "fresh.key"
    monkeypatch.setattr("sys.argv", ["rotate", "--generate-key", str(target)])
    rot.main()
    key = target.read_text().strip()
    Fernet(key.encode())
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert key not in capsys.readouterr().out
