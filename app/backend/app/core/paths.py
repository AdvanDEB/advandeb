"""
Filesystem containment for routes that take a path from the client.

Containment is decided on *resolved* paths — symlinks followed, ``..``
collapsed — and by path components, not string prefixes: ``startswith`` would
let ``~/dev`` admit ``~/dev_x``, and a lexical check would let a symlink inside
the root point anywhere.
"""
import os
import re
import uuid
from typing import Optional

from fastapi import HTTPException, status


def is_within(path: str, root: str) -> bool:
    """True if resolved ``path`` is ``root`` or lies beneath it."""
    path_real = os.path.realpath(path)
    root_real = os.path.realpath(root)
    try:
        return os.path.commonpath([path_real, root_real]) == root_real
    except ValueError:  # different drives / mixed absolute and relative
        return False


def resolve_within(root: str, relative: str) -> str:
    """Resolve ``relative`` against ``root``; 403 if it escapes the root.

    ``relative`` may be ``"."`` or ``""`` for the root itself. An absolute
    path is taken as-is and must still resolve inside ``root``.
    """
    candidate = os.path.join(root, relative) if relative not in ("", ".") else root
    resolved = os.path.realpath(candidate)
    if not is_within(resolved, root):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Path outside allowed root")
    return resolved


_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ ()+-]")


def safe_upload_filename(filename: Optional[str], *, extension: str) -> str:
    """Reduce a client-supplied filename to a single safe path component.

    Drops any directory part (POSIX or Windows separators), replaces characters
    outside a conservative set, and falls back to a random name when nothing
    usable is left. The result always ends in ``extension``.
    """
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = _UNSAFE_FILENAME_CHARS.sub("_", name).lstrip(".")
    stem = name[: -len(extension)] if name.lower().endswith(extension) else name
    stem = stem.strip(" ._")[:150]
    if not stem:
        stem = uuid.uuid4().hex
    return f"{stem}{extension}"
