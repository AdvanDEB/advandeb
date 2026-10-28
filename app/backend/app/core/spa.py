"""
Serve the built Vue SPA from FastAPI.

Client-side routes (/chat, /kb, /models/abc…) all need index.html, so a GET
catch-all answers every path no API route claimed. It must not answer for the
API itself: a mistyped or removed endpoint used to come back as
``200 text/html`` — the SPA shell — which a fetch() caller then failed to parse
as JSON, far from the real cause. Paths under the API and WebSocket prefixes
get FastAPI's ordinary JSON 404 instead.

A backend path that differs from a real route only by its trailing slash is a
404 too, not a redirect: the catch-all matches before FastAPI's slash
redirect can run, and a redirect would hide the caller's bug behind an extra
round trip (behind the tunnel the backend also sees http, so an absolute
Location would point a https page at http). The 404 names the route instead.
tests/test_frontend_api_paths.py checks every frontend call against the routes.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match

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


def slash_twin(request: Request) -> str | None:
    """The path with its trailing slash toggled, if that is a real route."""
    path = request.url.path
    twin = path[:-1] if path.endswith("/") else path + "/"
    scope = {**request.scope, "path": twin}
    for route in request.app.router.routes:
        if getattr(route, "name", None) == "spa_fallback":
            continue
        if route.matches(scope)[0] == Match.FULL:
            return twin
    return None


def mount_spa(app: FastAPI, dist: Path) -> None:
    """Mount ``dist/assets`` and the index.html fallback. Register last."""
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request):
        if is_backend_path(full_path):
            twin = slash_twin(request)
            detail = f"Not Found. The route is {twin}" if twin else "Not Found"
            raise HTTPException(status_code=404, detail=detail)
        static = public_file(dist, full_path)
        if static is not None and static.name != "index.html":
            return FileResponse(static)
        return FileResponse(
            dist / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
