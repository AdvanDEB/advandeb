import os
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Any, Dict, List

from app.core.dependencies import require_curator

router = APIRouter()

FS_ROOT = os.path.realpath(os.path.expanduser(os.environ.get("FS_ROOT", "~/dev")))
DEFAULT_PATH = os.path.expanduser("~/dev/advandeb_auxiliary")


@router.get("/browse")
async def browse(
    path: str = Query(default=""),
    current_user: dict = Depends(require_curator),
) -> Dict[str, Any]:
    """Browse a directory within the allowed root."""
    target = path if path else DEFAULT_PATH
    resolved = os.path.realpath(os.path.expanduser(target))

    if not resolved.startswith(FS_ROOT):
        raise HTTPException(status_code=403, detail="Path outside allowed root")
    if not os.path.exists(resolved):
        raise HTTPException(status_code=404, detail=f"Path not found: {target}")
    if not os.path.isdir(resolved):
        raise HTTPException(status_code=400, detail=f"Not a directory: {target}")

    entries: List[Dict[str, Any]] = []
    try:
        with os.scandir(resolved) as it:
            items = sorted(it, key=lambda e: (not e.is_dir(), e.name.lower()))
            for entry in items:
                try:
                    stat = entry.stat(follow_symlinks=False)
                    entries.append({
                        "name": entry.name,
                        "type": "dir" if entry.is_dir() else "file",
                        "size": stat.st_size if entry.is_file() else None,
                        "path": resolved + "/" + entry.name,
                    })
                except OSError:
                    pass
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    parent = str(os.path.dirname(resolved))
    if not parent.startswith(FS_ROOT):
        parent = None

    return {"path": resolved, "parent": parent, "entries": entries}
