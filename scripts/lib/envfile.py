"""Edit app/backend/.env safely: backups and rewrites are mode 600, values never printed."""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def env_file() -> Path:
    configured = os.environ.get("ADVANDEB_ENV_FILE")
    return Path(configured).expanduser() if configured else REPO_ROOT / "app" / "backend" / ".env"


def load_values(path: Path) -> dict:
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def write_private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` with mode 600 from the first byte."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def backup(path: Path) -> Path:
    target = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, target)
    os.chmod(target, 0o600)
    return target


def set_line(lines: list[str], key: str, value: str | None) -> list[str]:
    """Replace (or append, or with value=None drop) the ``key=`` line."""
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(key)}\s*=")
    out, done = [], False
    for line in lines:
        if pattern.match(line):
            if value is not None and not done:
                out.append(f"{key}={value}\n")
                done = True
            continue
        out.append(line)
    if value is not None and not done:
        out.append(f"{key}={value}\n")
    return out


def drop_comments_matching(lines: list[str], word: str) -> list[str]:
    return [l for l in lines if not re.match(rf"^\s*#.*\b{re.escape(word)}\b", l, re.IGNORECASE)]


def rewrite(path: Path, edit) -> Path:
    """Back up ``path``, apply ``edit(lines) -> lines``, write it back as 600."""
    saved = backup(path)
    lines = path.read_text().splitlines(keepends=True)
    write_private(path, "".join(edit(lines)))
    return saved
