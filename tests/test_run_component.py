"""scripts/run_component.py — each stack component gets only the env it needs."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_component.py"


@pytest.fixture
def rc(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "JWT_SECRET_KEY=jwt\n"
        "GOOGLE_CLIENT_SECRET=google\n"
        "DEFAULT_CHAT_API_KEY=shared\n"
        "LLM_KEY_ENCRYPTION_KEY=fernet\n"
        "ARANGO_PASSWORD=arango-from-file\n"
        "MONGODB_URI=mongodb://u:p@localhost:27017\n"
        "CHAT_MODE=react\n"
        "GITHUB_OAUTH_CLIENT_ID=gh\n"
        "ADVANDEB_MCP_BIND=127.0.0.1:8080\n"
    )
    monkeypatch.setenv("ADVANDEB_ENV_FILE", str(env_file))
    for name in ("JWT_SECRET_KEY", "ARANGO_PASSWORD", "MONGODB_URI", "LLM_KEY_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("run_component", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_gets_kb_settings_but_no_web_secrets(rc):
    env = rc.build_env("retrieval_agent")
    assert env["ARANGO_PASSWORD"] == "arango-from-file"   # start_all.sh passed ""
    assert env["MONGODB_URI"].startswith("mongodb://")
    assert env["CHAT_MODE"] == "react"
    for secret in ("JWT_SECRET_KEY", "GOOGLE_CLIENT_SECRET", "DEFAULT_CHAT_API_KEY",
                   "LLM_KEY_ENCRYPTION_KEY", "GITHUB_OAUTH_CLIENT_ID", "ADVANDEB_MCP_BIND"):
        assert secret not in env


def test_chatbot_agent_also_gets_byok_keys(rc):
    env = rc.build_env("chatbot_agent")
    assert env["LLM_KEY_ENCRYPTION_KEY"] == "fernet"
    assert env["GITHUB_OAUTH_CLIENT_ID"] == "gh"
    assert "JWT_SECRET_KEY" not in env and "DEFAULT_CHAT_API_KEY" not in env


def test_gateway_gets_only_its_own_settings(rc):
    env = rc.build_env("gateway")
    assert env["ADVANDEB_MCP_BIND"] == "127.0.0.1:8080"
    for name in ("ARANGO_PASSWORD", "MONGODB_URI", "JWT_SECRET_KEY", "CHAT_MODE"):
        assert name not in env


def test_process_env_overrides_file(rc, monkeypatch):
    monkeypatch.setenv("ARANGO_PASSWORD", "from-systemd")
    assert rc.build_env("curator_agent")["ARANGO_PASSWORD"] == "from-systemd"


def test_unrelated_parent_env_is_not_inherited(rc, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nope")
    assert "AWS_SECRET_ACCESS_KEY" not in rc.build_env("synthesis_agent")


def test_unknown_component_is_refused(rc):
    with pytest.raises(SystemExit):
        rc.command("not_an_agent")
