"""
The SPA catch-all used to answer unknown /api/* paths with 200 and index.html,
so a removed or mistyped endpoint surfaced in the browser as a JSON parse
error. It must 404 as JSON, while client-side routes still get the shell and
real files at the top of dist/ are served as themselves.

Nothing here touches a database or the filesystem outside tmp_path.
"""
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.core.spa import is_backend_path, mount_spa


@pytest.fixture
async def client(tmp_path: Path):
    # httpx's ASGI transport rather than starlette's TestClient, which does not
    # work against the httpx this environment pins.
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('ok')")
    (tmp_path / "index.html").write_text("<!doctype html><div id=app></div>")
    (tmp_path / "robots.txt").write_text("User-agent: *\n")
    (tmp_path.parent / "secret.txt").write_text("outside dist")

    app = FastAPI()

    @app.get("/api/ping")
    async def ping():
        return {"pong": True}

    @app.post("/api/things")
    async def make_thing():
        return {"made": True}

    mount_spa(app, tmp_path)   # last, as in app.main
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("path", ["/api/nope", "/api/kb/no-such-thing", "/api", "/api/", "/ws/nope"])
@pytest.mark.asyncio
async def test_unknown_backend_paths_are_json_404(client, path):
    r = await client.get(path)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"detail": "Not Found"}


@pytest.mark.asyncio
async def test_real_api_routes_still_win(client):
    r = await client.get("/api/ping")
    assert r.status_code == 200 and r.json() == {"pong": True}
    assert (await client.post("/api/things")).json() == {"made": True}


@pytest.mark.parametrize("path", ["/", "/chat", "/kb", "/models/abc123", "/apiary", "/wsx/y"])
@pytest.mark.asyncio
async def test_client_routes_get_the_spa_shell(client, path):
    r = await client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "id=app" in r.text
    assert "no-store" in r.headers["cache-control"]


@pytest.mark.asyncio
async def test_assets_are_served_and_missing_ones_404(client):
    assert (await client.get("/assets/app.js")).status_code == 200
    assert (await client.get("/assets/missing.js")).status_code == 404


@pytest.mark.asyncio
async def test_root_files_from_public_are_served_as_themselves(client):
    r = await client.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text.startswith("User-agent")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"])
async def test_nothing_outside_dist_is_reachable(client, path):
    r = await client.get(path)
    assert "outside dist" not in r.text


@pytest.mark.parametrize("path,expected", [
    ("api", True), ("api/x/y", True), ("ws/chat/1", True),
    ("", False), ("apiary", False), ("kb/api", False),
])
def test_is_backend_path(path, expected):
    assert is_backend_path(path) is expected
