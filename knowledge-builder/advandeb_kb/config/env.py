"""
One place that decides where AdvanDEB configuration comes from.

The web app (pydantic Settings) and the KB library (this package) used to
read configuration differently: the app read ``.env`` from whatever the
current directory happened to be, the KB read only ``os.environ`` at import
time, and the two spelled the same setting differently (MONGODB_URI vs
MONGODB_URL, KB_DB_NAME vs DATABASE_NAME). Started from the wrong directory,
or without the shell having exported the file, the KB silently fell back to
defaults (an empty ARANGO_PASSWORD, an unauthenticated Mongo URI).

Resolution order for every value, here and in the app:

    1. the process environment (systemd Environment=/EnvironmentFile=, the
       component launcher, an explicit ``export``)
    2. the env file named by ``ADVANDEB_ENV_FILE``; when that variable is
       unset, ``app/backend/.env`` in this checkout
    3. the code default

``ADVANDEB_ENV_FILE=""`` (set but empty) disables step 2. The test suite does
that so a developer's production ``.env`` can never leak into a test run.

Values read from the file are *not* copied into ``os.environ``: a script that
imports this package does not thereby export every secret in the file to
its child processes.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

#: knowledge-builder/advandeb_kb/config/env.py → repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / "app" / "backend" / ".env"


def env_file_path() -> Optional[Path]:
    """Return the env file to read, or None when there is none / it is disabled."""
    configured = os.environ.get("ADVANDEB_ENV_FILE")
    if configured is not None:
        if not configured.strip():
            return None
        path = Path(configured).expanduser()
        return path if path.is_file() else None
    return DEFAULT_ENV_FILE if DEFAULT_ENV_FILE.is_file() else None


@lru_cache(maxsize=None)
def _file_values(path: Optional[Path]) -> dict:
    if path is None:
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def file_values() -> dict:
    """Values from the env file (empty when there is no file)."""
    return _file_values(env_file_path())


def getenv(name: str, default: str = "", aliases: Iterable[str] = ()) -> str:
    """Resolve ``name`` (then each deprecated alias) from env, then the file.

    The process environment wins over the file for *every* spelling before the
    file is consulted, so an operator's explicit ``MONGODB_URL=...`` override
    is never shadowed by a ``MONGODB_URI`` line sitting in the file.
    """
    names = (name, *aliases)
    for n in names:
        value = os.environ.get(n)
        if value is not None:
            return value
    values = file_values()
    for n in names:
        if n in values:
            return values[n]
    return default


def getenv_int(name: str, default: int, aliases: Iterable[str] = ()) -> int:
    return int(getenv(name, str(default), aliases))


def getenv_bool(name: str, default: bool, aliases: Iterable[str] = ()) -> bool:
    return getenv(name, "true" if default else "false", aliases).strip().lower() in (
        "1", "true", "yes", "on",
    )
