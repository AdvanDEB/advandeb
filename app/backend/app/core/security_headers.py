"""
Security response headers, and the endpoint that collects CSP reports.

Every HTTP response gets nosniff, a referrer policy, anti-framing
(X-Frame-Options and CSP frame-ancestors), a Permissions-Policy that turns off
device APIs the app never uses, and HSTS (settings.SECURITY_HSTS_MAX_AGE).

The Content-Security-Policy for the pages is sent as *Report-Only*. It was
derived from what the production build loads (see PAGE_CSP below), but Plotly,
KaTeX, the cosmos.gl WebGL graph and the graph worker cannot be exercised
against it without a deploy. Violations are POSTed to /api/csp-report and
logged to logs/csp-reports.log; once that log stays quiet the same string can
become the enforced policy. API responses are JSON or event streams that are never rendered as a
document, so they get a strict policy enforced from the start.

In production nginx serves index.html and /assets itself and proxies only
/api and /ws here, so for the page headers to reach browsers nginx has to send
them as well (dev-log F-007 has the snippet). Locally, and wherever the backend
serves the SPA (app.core.spa), this middleware covers the pages too.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time

from fastapi import APIRouter, Request, Response
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.limiter import limiter

logger = logging.getLogger(__name__)

CSP_REPORT_PATH = "/api/csp-report"

# What the built app loads, directive by directive:
#  script   only /assets/*.js module scripts; index.html has no inline script
#           and nothing in the bundles calls eval / new Function on a live path
#  style    /assets/*.css, plus inline: Plotly injects a <style> element, and
#           KaTeX and sanitised markdown carry style="" attributes
#  img      own files, data:/blob: (Plotly, exports), Google profile pictures
#           (users.avatar_url comes from the Google id_token "picture")
#  font     KaTeX's font files under /assets
#  connect  /api fetches and the /ws and /api/tdeb/ws sockets, all same-origin
#  worker   the graph-artifact worker, a file under /assets
# Google sign-in is a top-level navigation and a server-side code exchange, so
# it needs no entry here.
PAGE_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https://*.googleusercontent.com",
    "font-src 'self' data:",
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    f"report-uri {CSP_REPORT_PATH}",
])

API_CSP = "default-src 'none'; frame-ancestors 'none'"

PERMISSIONS_POLICY = ", ".join(f"{feature}=()" for feature in (
    "accelerometer", "camera", "geolocation", "gyroscope",
    "magnetometer", "microphone", "payment", "usb",
))


def security_headers(path: str, hsts_max_age: int) -> list[tuple[str, str]]:
    """The headers for a response to ``path``."""
    headers = [
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("X-Frame-Options", "DENY"),
        ("Permissions-Policy", PERMISSIONS_POLICY),
    ]
    if hsts_max_age > 0:
        # Browsers ignore it over plain HTTP (RFC 6797 §8.1), so it is safe to
        # send unconditionally — which matters here: behind the Cloudflare
        # tunnel and nginx the backend only ever sees http. No
        # includeSubDomains: other services live on advandeb.com subdomains.
        headers.append(("Strict-Transport-Security", f"max-age={hsts_max_age}"))
    if path == "/api" or path.startswith("/api/"):
        headers.append(("Content-Security-Policy", API_CSP))
    else:
        # Anti-framing is enforced now; the rest is reported first.
        headers.append(("Content-Security-Policy", "frame-ancestors 'none'"))
        headers.append(("Content-Security-Policy-Report-Only", PAGE_CSP))
    return headers


class SecurityHeadersMiddleware:
    """Pure ASGI, so streaming responses (SSE) pass through untouched.

    A header a route set itself is left alone.
    """

    def __init__(self, app: ASGIApp, hsts_max_age: int = 0) -> None:
        self.app = app
        self.hsts_max_age = hsts_max_age

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        extra = security_headers(scope["path"], self.hsts_max_age)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in extra:
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ── CSP violation reports ─────────────────────────────────────────────────── #
#
# A public, unauthenticated endpoint whose job is to accept arbitrary bodies,
# so it reads at most _MAX_REPORT_BYTES (refusing a larger Content-Length
# unread), survives any JSON (deep nesting raised RecursionError: a 500 and a
# traceback), and logs to its own small file, deduplicated, so a flood or a
# noisy browser extension cannot rotate real errors out of the shared app log.

router = APIRouter()

_MAX_REPORT_BYTES = 16 * 1024
_REPORTED_FIELDS = (
    "document-uri", "violated-directive", "effective-directive",
    "blocked-uri", "source-file", "line-number", "disposition",
)
# Extensions inject scripts and styles into every page; their violations are
# not ours to fix.
_EXTENSION_SCHEMES = ("chrome-extension:", "moz-extension:", "safari-extension:",
                      "safari-web-extension:", "ms-browser-extension:")
_DEDUPE_SECONDS = 600
_DEDUPE_MAX = 500

csp_logger = logging.getLogger("advandeb.csp")
_seen: "dict[tuple, list[float | int]]" = {}   # signature -> [last logged at, suppressed since]


def _csp_log_handler() -> None:
    """Give the CSP logger its own 1 MB x 2 file next to the app log, once."""
    if csp_logger.handlers:
        return
    path = os.path.join(os.path.dirname(settings.LOG_FILE) or ".", "csp-reports.log")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))
    csp_logger.addHandler(handler)
    csp_logger.setLevel(logging.INFO)
    csp_logger.propagate = False


def _clip(value: object) -> str:
    # repr() keeps a hostile report from writing newlines into the log.
    return repr(str(value)[:200])


async def _read_capped(request: Request) -> bytes | None:
    """The body, or None if it is (or claims to be) over the cap."""
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > _MAX_REPORT_BYTES):
        return None
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > _MAX_REPORT_BYTES:
            return None
    return bytes(body)


def _record(report: dict, now: float) -> None:
    if any(str(report.get(k, "")).startswith(_EXTENSION_SCHEMES)
           for k in ("blocked-uri", "source-file")):
        return
    signature = tuple(str(report.get(k, ""))[:200] for k in
                      ("violated-directive", "effective-directive", "blocked-uri", "source-file"))
    entry = _seen.get(signature)
    if entry is not None and now - entry[0] < _DEDUPE_SECONDS:
        entry[1] += 1
        return
    suppressed = entry[1] if entry is not None else 0
    if len(_seen) >= _DEDUPE_MAX:
        _seen.clear()
    _seen[signature] = [now, 0]
    _csp_log_handler()
    csp_logger.warning(
        "CSP report: %s%s",
        " ".join(f"{k}={_clip(report[k])}" for k in _REPORTED_FIELDS if k in report),
        f" (+{suppressed} identical in the last {_DEDUPE_SECONDS // 60} min)" if suppressed else "",
    )


@router.post("/csp-report", status_code=204, include_in_schema=False)
@limiter.limit("60/minute")
async def csp_report(request: Request) -> Response:
    """Log a browser's CSP violation report (report-uri format). Public.

    Rate-limited, size-capped before reading, parse-safe; a fixed set of fields
    goes to logs/csp-reports.log, deduplicated, extension noise dropped.
    204, or 413 for a body over the cap.
    """
    body = await _read_capped(request)
    if body is None:
        return Response(status_code=413)
    try:
        report = json.loads(body).get("csp-report", {})
    except (ValueError, AttributeError, RecursionError):
        return Response(status_code=204)
    if isinstance(report, dict) and report:
        _record(report, time.monotonic())
    return Response(status_code=204)
