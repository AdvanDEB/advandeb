#!/usr/bin/env python3
"""
run_component.py — exec one AdvanDEB stack component with only the
environment it needs.

    run_component.py gateway
    run_component.py <agent>        e.g. retrieval_agent, chatbot_agent
    run_component.py --list         components and the variables each gets
    run_component.py --check NAME   print the *names* it would pass, then exit

Used by the systemd units (advandeb-gateway.service, advandeb-agent@.service)
and by scripts/start_stack.sh, so a component is started the same way in both.

Why: start_stack.sh used to ``source`` the whole app/backend/.env with
allexport, so all seven processes inherited the JWT signing key, the Google
client secret and the shared chat API key, none of which any of them uses.
Here each component gets an allowlist. Values come from the process
environment first (systemd Environment=, an explicit export), then from the
env file — the same order as the app and the KB library.

Never prints values, only names.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = REPO_ROOT / "knowledge-builder"
MCP_DIR = REPO_ROOT / "mcp"
GATEWAY_BIN = MCP_DIR / "target" / "release" / "advandeb-mcp"

AGENTS = (
    "retrieval_agent",
    "graph_explorer_agent",
    "synthesis_agent",
    "query_planner_agent",
    "curator_agent",
    "chatbot_agent",
)

# Runtime plumbing passed through from the parent when present. Nothing secret.
PASSTHROUGH = (
    "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TZ", "TMPDIR",
    # systemd: journald stream detection, sd_notify, unit identity
    "INVOCATION_ID", "JOURNAL_STREAM", "NOTIFY_SOCKET",
    # model caches / GPU selection for the embedding model
    "HF_HOME", "TRANSFORMERS_CACHE", "SENTENCE_TRANSFORMERS_HOME", "TORCH_HOME",
    "CUDA_VISIBLE_DEVICES",
    "ADVANDEB_ENV_FILE",
)

# What every KB agent reads (advandeb_kb/config/settings.py, including the
# deprecated aliases so an older .env keeps working).
KB_AGENT_EXACT = (
    "MONGODB_URI", "MONGODB_URL", "KB_DB_NAME", "DATABASE_NAME",
    "MONGODB_DB_NAME", "CHAT_STORE_DB_NAME",
    "ARANGO_URL", "ARANGO_DB_NAME", "ARANGO_USERNAME", "ARANGO_PASSWORD",
    "OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_NUM_CTX",
    "REDIS_URL", "PAPERS_ROOT", "INGESTION_CONCURRENCY", "OPENALEX_EMAIL",
    "CHROMA_PERSIST_DIR", "CHROMA_COLLECTION", "EMBEDDING_MODEL",
    "MAX_FILE_SIZE", "UPLOAD_DIR", "LOG_LEVEL", "ENVIRONMENT",
)
KB_AGENT_PREFIXES = ("CHAT_",)

# chatbot_agent decrypts BYOK keys and refreshes GitHub tokens itself.
EXTRA = {
    "chatbot_agent": (
        "LLM_KEY_ENCRYPTION_KEY", "LLM_KEY_ENCRYPTION_KEY_PREVIOUS",
        "GITHUB_OAUTH_CLIENT_ID",
    ),
}

GATEWAY_EXACT = ("RUST_LOG", "RUST_BACKTRACE")
GATEWAY_PREFIXES = ("ADVANDEB_MCP_",)


def env_file() -> Path | None:
    configured = os.environ.get("ADVANDEB_ENV_FILE")
    if configured is not None:
        if not configured.strip():
            return None
        path = Path(configured).expanduser()
    else:
        path = REPO_ROOT / "app" / "backend" / ".env"
    return path if path.is_file() else None


def file_values(path: Path | None) -> dict:
    if path is None:
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def allowed(component: str, name: str) -> bool:
    if component == "gateway":
        return name in GATEWAY_EXACT or name.startswith(GATEWAY_PREFIXES)
    return (
        name in KB_AGENT_EXACT
        or name.startswith(KB_AGENT_PREFIXES)
        or name in EXTRA.get(component, ())
    )


def build_env(component: str) -> dict:
    env = {k: os.environ[k] for k in PASSTHROUGH if k in os.environ}
    python_bin = str(Path(sys.executable).parent)
    env["PATH"] = f"{python_bin}:/usr/local/bin:/usr/bin:/bin"
    env["PYTHONUNBUFFERED"] = "1"
    env["NO_COLOR"] = "1"   # libraries that colourise logs; journald/files are not terminals

    merged = file_values(env_file())
    merged.update(os.environ)          # the process environment wins
    for name, value in merged.items():
        if allowed(component, name):
            env[name] = value
    return env


def command(component: str) -> tuple[list[str], Path]:
    if component == "gateway":
        if not os.access(GATEWAY_BIN, os.X_OK):
            sys.exit(
                f"run_component: gateway binary missing or not executable: {GATEWAY_BIN}\n"
                f"               build it with: cd {MCP_DIR} && cargo build --release"
            )
        # The gateway finds config/default.toml relative to its working directory.
        return [str(GATEWAY_BIN)], MCP_DIR
    if component in AGENTS:
        return [sys.executable, "-m", f"advandeb_kb.agents.{component}"], KB_DIR
    sys.exit(f"run_component: unknown component {component!r}; one of: gateway, {', '.join(AGENTS)}")


def main(argv: list[str]) -> None:
    if argv[:1] == ["--list"]:
        for component in ("gateway", *AGENTS):
            print(f"{component}: {' '.join(sorted(k for k in build_env(component) if allowed(component, k)))}")
        return
    if argv[:1] == ["--check"] and len(argv) == 2:
        env = build_env(argv[1])
        command(argv[1])
        print("\n".join(sorted(env)))
        return
    if len(argv) != 1:
        sys.exit(__doc__)

    component = argv[0]
    cmd, cwd = command(component)
    env = build_env(component)
    os.chdir(cwd)
    os.execvpe(cmd[0], cmd, env)


if __name__ == "__main__":
    main(sys.argv[1:])
