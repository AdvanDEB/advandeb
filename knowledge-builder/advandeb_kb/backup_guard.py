"""Refuse irreversible operations unless a recent, successful backup exists.

``app/backend/app/core/dbguard.py`` answers one question: is this database
unmistakably scratch? This module answers the other half. Some operations
*must* touch production — the KB reset, a migration wipe, a schema rebuild —
and for those the question is whether a backup of exactly that store finished
recently enough that the operation can be undone. Production collections have
already been lost once with nothing to restore from (commit 0cd580c); an
irreversible operation without a restore point is the failure this prevents.

The backup job (``scripts/backup/advandeb_backup.py``) writes one directory per
run under ``ADVANDEB_BACKUP_DIR`` (default ``~/backups/advandeb``), each with a
``manifest.json`` recording a status per component (``mongo:<db>``,
``arango:<db>``, ``chroma``). A component counts only if it individually
succeeded; directories still named ``*.partial`` are runs that never finished
and never count.

Usage::

    from advandeb_kb.backup_guard import require_recent_backup
    require_recent_backup("arango:advandeb_kb", max_age_hours=26)   # raises
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union

MANIFEST_NAME = "manifest.json"
PARTIAL_SUFFIX = ".partial"

PathLike = Union[str, Path]


class NoRecentBackupError(RuntimeError):
    """Raised when an irreversible operation has no recent restore point."""


def backup_root() -> Path:
    configured = os.environ.get("ADVANDEB_BACKUP_DIR")
    return Path(configured) if configured else Path.home() / "backups" / "advandeb"


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def iter_manifests(root: Optional[PathLike] = None) -> Iterator[Dict[str, Any]]:
    """Yield every readable manifest of a finished run, with its ``_path``."""
    base = Path(root) if root else backup_root()
    if not base.is_dir():
        return
    for run in base.iterdir():
        manifest = run / MANIFEST_NAME
        if not run.is_dir() or run.name.endswith(PARTIAL_SUFFIX) or not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data["_path"] = str(run)
            yield data


def latest_backup(component: str, root: Optional[PathLike] = None) -> Optional[Dict[str, Any]]:
    """The newest manifest in which ``component`` succeeded, or None."""
    best, best_ts = None, None
    for manifest in iter_manifests(root):
        entry = (manifest.get("components") or {}).get(component)
        if not isinstance(entry, dict) or entry.get("status") != "ok":
            continue
        ts = _parse_ts(manifest.get("finished_at"))
        if ts is None:
            continue
        if best_ts is None or ts > best_ts:
            best, best_ts = manifest, ts
    return best


def backup_age_hours(manifest: Dict[str, Any], now: Optional[datetime] = None) -> float:
    finished = _parse_ts(manifest.get("finished_at"))
    if finished is None:
        return float("inf")
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - finished).total_seconds() / 3600)


def require_recent_backup(
    component: str,
    max_age_hours: float = 26,
    root: Optional[PathLike] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return the latest successful backup of ``component``, or raise.

    The default of 26 hours is one daily backup plus slack for a late run.
    """
    base = Path(root) if root else backup_root()
    manifest = latest_backup(component, base)
    if manifest is None:
        raise NoRecentBackupError(
            f"no successful backup of {component!r} under {base}. Run "
            f"scripts/backup/advandeb_backup.py first: this operation cannot "
            f"be undone without one."
        )
    age = backup_age_hours(manifest, now)
    if age > max_age_hours:
        raise NoRecentBackupError(
            f"the latest successful backup of {component!r} is {age:.1f} h old "
            f"(limit {max_age_hours:g} h): {manifest['_path']}. Run a fresh "
            f"backup first."
        )
    return manifest
