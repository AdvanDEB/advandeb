"""
Serve the built Vue SPA from FastAPI.

Client-side routes (/chat, /kb, /models/abc…) all need index.html, so a GET
catch-all answers every path no API route claimed. It must not answer for the
API itself: a mistyped or removed endpoint used to come back as
``200 text/html`` — the SPA shell — which a fetch() caller then failed to parse
as JSON, far from the real cause. Paths under the API and WebSocket prefixes
get FastAPI's ordinary JSON 404 instead.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# First path segments that belong to the backend, never to the SPA.
BACKEND_PREFIXES = frozenset({"api", "ws"})


def is_backend_path(full_path: str) -> bool:
    """True for ``api``, ``api/…``, ``ws/…`` — but not ``apiary``."""
    return full_path.split("/", 1)[0] in BACKEND_PREFIXES


def public_file(dist: Path, full_path: str) -> Path | None:
    """A real file at the top of ``dist`` (favicon, robots.txt, og-image…).

    Vite copies ``public/`` there. In production nginx serves these itself;
    without this, a request that reaches the backend directly got index.html
    for /favicon.ico and /robots.txt. Only files inside ``dist`` qualify —
    the resolved path must not climb out of it.
    """
    if not full_path:
        return None
    root = dist.resolve()
    candidate = (root / full_path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def mount_spa(app: FastAPI, dist: Path) -> None:
    """Mount ``dist/assets`` and the index.html fallback. Register last."""
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if is_backend_path(full_path):
            raise HTTPException(status_code=404, detail="Not Found")
        static = public_file(dist, full_path)
        if static is not None and static.name != "index.html":
            return FileResponse(static)
        return FileResponse(
            dist / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
