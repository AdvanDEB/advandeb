"""
Security response headers (F-007). Before: no response from the backend carried
nosniff, a referrer policy, anti-framing, a Permissions-Policy, HSTS or any CSP,
so the app could be framed and nothing limited what a page may load.

The app-level tests use the real ``app.main.app`` through the shared ``client``
fixture (in-memory Mongo stand-in, no lifespan). The middleware tests mount it
on a bare app with an SPA directory in tmp_path. No database, no network.
"""
import logging
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from app.core.security_headers import (
    API_CSP, PAGE_CSP, SecurityHeadersMiddleware, security_headers,
)
from app.core.spa import mount_spa

COMMON = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-frame-options": "DENY",
}


def _assert_common(headers):
    for name, value in COMMON.items():
        assert headers.get(name) == value, name
    assert "camera=()" in headers["permissions-policy"]
    assert "microphone=()" in headers["permissions-policy"]


# ── the real application ──────────────────────────────────────────────────── #

def test_api_responses_carry_the_headers_and_a_strict_csp(client):
    r = client.get("/api/info")
    assert r.status_code == 200
    _assert_common(r.headers)
    assert r.headers["content-security-policy"] == API_CSP
    assert "content-security-policy-report-only" not in r.headers
    assert r.headers["strict-transport-security"] == "max-age=86400"


def test_errors_and_auth_failures_carry_them_too(client):
    for r in (client.get("/api/no-such-endpoint"), client.get("/api/users/me")):
        assert r.status_code in (401, 404)
        _assert_common(r.headers)
        assert r.headers["content-security-policy"] == API_CSP


def test_cors_preflight_carries_them(client):
    r = client.options("/api/info", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    _assert_common(r.headers)


def test_hsts_has_no_include_subdomains():
    # Other services run on advandeb.com subdomains; one of them going
    # HTTPS-only by accident is not this app's call.
    headers = dict(security_headers("/", 86400))
    assert headers["Strict-Transport-Security"] == "max-age=86400"
    assert "includeSubDomains" not in headers["Strict-Transport-Security"]
    assert "Strict-Transport-Security" not in dict(security_headers("/", 0))


# ── the SPA, when the backend serves it ───────────────────────────────────── #

@pytest.fixture
async def spa_client(tmp_path: Path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('ok')")
    (tmp_path / "index.html").write_text("<!doctype html><div id=app></div>")
    app = FastAPI()

    @app.get("/api/stream")
    async def stream():
        async def chunks():
            yield b"data: one\n\n"
            yield b"data: two\n\n"
        return StreamingResponse(chunks(), media_type="text/event-stream")

    @app.get("/api/own-header")
    async def own_header():
        from fastapi.responses import JSONResponse
        return JSONResponse({}, headers={"X-Frame-Options": "SAMEORIGIN"})

    mount_spa(app, tmp_path)
    app.add_middleware(SecurityHeadersMiddleware, hsts_max_age=3600)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/login", "/assets/app.js"])
async def test_pages_get_anti_framing_enforced_and_the_csp_report_only(spa_client, path):
    r = await spa_client.get(path)
    assert r.status_code == 200
    _assert_common(r.headers)
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert r.headers["content-security-policy-report-only"] == PAGE_CSP
    assert r.headers["strict-transport-security"] == "max-age=3600"


async def test_streaming_responses_pass_through(spa_client):
    r = await spa_client.get("/api/stream")
    assert r.text == "data: one\n\ndata: two\n\n"
    assert r.headers["content-security-policy"] == API_CSP


async def test_a_route_header_is_not_overridden(spa_client):
    r = await spa_client.get("/api/own-header")
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_page_csp_names_what_the_build_needs():
    directives = dict(d.split(" ", 1) for d in PAGE_CSP.split("; "))
    assert directives["script-src"] == "'self'"          # no unsafe-inline / unsafe-eval
    assert "'unsafe-inline'" in directives["style-src"]   # Plotly <style>, KaTeX style=""
    assert "blob:" in directives["worker-src"]
    assert directives["object-src"] == "'none'"
    assert directives["frame-ancestors"] == "'none'"
    assert directives["report-uri"] == "/api/csp-report"


# ── CSP reports ───────────────────────────────────────────────────────────── #

def test_csp_report_is_logged_and_answered_204(client, caplog):
    report = {"csp-report": {
        "document-uri": "https://advandeb.com/models/1",
        "violated-directive": "style-src-elem",
        "blocked-uri": "inline",
        "original-policy": "x" * 5000,   # not logged
    }}
    with caplog.at_level(logging.WARNING, logger="app.core.security_headers"):
        r = client.post("/api/csp-report", json=report,
                        headers={"Content-Type": "application/csp-report"})
    assert r.status_code == 204
    line = caplog.records[-1].getMessage()
    assert "violated-directive='style-src-elem'" in line
    assert "original-policy" not in line


def test_csp_report_tolerates_junk_and_cannot_inject_log_lines(client, caplog):
    assert client.post("/api/csp-report", content=b"not json").status_code == 204
    assert client.post("/api/csp-report", content=b"x" * 20000).status_code == 204
    with caplog.at_level(logging.WARNING, logger="app.core.security_headers"):
        client.post("/api/csp-report", json={"csp-report": {"blocked-uri": "a\nFAKE LOG LINE"}})
    assert "\n" not in caplog.records[-1].getMessage()
