"""
Prometheus instrumentation for the web app.

Exposes, on ``GET /metrics`` (loopback only — see ``metrics_endpoint``):

* ``advandeb_http_requests_total`` / ``advandeb_http_request_duration_seconds``
  by method, route *template* and status — the 5xx alert keys on these;
* ``advandeb_websocket_connections`` — open browser chat sockets;
* ``advandeb_chat_turns_total`` / ``advandeb_chat_turn_duration_seconds`` by
  path (``default`` shared NVIDIA key, ``byok``, ``agent`` = chatbot_agent)
  and outcome — the shared key's intermittent 503s surface here;
* ``advandeb_dependency_up`` / ``advandeb_dependency_probe_seconds`` for
  MongoDB, ArangoDB and Ollama, probed at scrape time (none of the three
  exposes Prometheus metrics without an extra exporter);
* the KB library's rebuild-queue metrics and the process collector.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from advandeb_kb import metrics as kb_metrics
from advandeb_kb.metrics import HTTP_BUCKETS, LLM_BUCKETS, counter, gauge, histogram

from app.core.config import settings

HTTP_REQUESTS = counter(
    "advandeb_http_requests_total",
    "HTTP requests served by the web app",
    ("method", "route", "status"),
)
HTTP_DURATION = histogram(
    "advandeb_http_request_duration_seconds",
    "HTTP request wall time, until the last body byte is sent",
    ("method", "route"),
    buckets=HTTP_BUCKETS,
)
HTTP_IN_FLIGHT = gauge(
    "advandeb_http_requests_in_flight",
    "HTTP requests currently being served",
)
WS_CONNECTIONS = gauge(
    "advandeb_websocket_connections",
    "Open WebSocket connections (browser chat, graph streams)",
)
CHAT_TURNS = counter(
    "advandeb_chat_turns_total",
    "Streamed chat turns by LLM path and outcome",
    ("path", "outcome"),
)
CHAT_DURATION = histogram(
    "advandeb_chat_turn_duration_seconds",
    "Wall time of one streamed chat turn, first byte in to final answer out",
    ("path", "outcome"),
    buckets=LLM_BUCKETS,
)
DEPENDENCY_UP = gauge(
    "advandeb_dependency_up",
    "1 if the dependency answered its probe during the last scrape",
    ("dependency",),
)
DEPENDENCY_PROBE = gauge(
    "advandeb_dependency_probe_seconds",
    "Duration of the last dependency probe",
    ("dependency",),
)

PROBE_TIMEOUT_SECONDS = 2.0


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _route_template(app, scope) -> str:
    """The matched route's path template, so /api/users/<id> is one series.

    Starlette 0.27 does not record the matched route in the scope, so this
    re-runs the router's matcher (the same thing prometheus-fastapi-
    instrumentator does). Unmatched paths share one label to bound cardinality.
    """
    for route in getattr(app, "routes", ()):
        try:
            match, _ = route.matches(scope)
        except Exception:  # noqa: BLE001 - a route that cannot match this scope
            continue
        if match == Match.FULL:
            return getattr(route, "path", "<unnamed>")
    return "<unmatched>"


class PrometheusMiddleware:
    """Pure ASGI middleware: times HTTP requests, counts open WebSockets.

    Pure ASGI rather than BaseHTTPMiddleware so streamed responses and
    WebSockets pass through untouched.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "websocket":
            WS_CONNECTIONS.inc()
            try:
                await self.app(scope, receive, send)
            finally:
                WS_CONNECTIONS.dec()
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status = {"code": 500}
        started = time.perf_counter()

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        HTTP_IN_FLIGHT.inc()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            HTTP_IN_FLIGHT.dec()
            route = _route_template(scope.get("app") or self.app, scope)
            method = scope.get("method", "GET")
            HTTP_REQUESTS.labels(method, route, str(status["code"])).inc()
            HTTP_DURATION.labels(method, route).observe(time.perf_counter() - started)


# ── Chat turns ───────────────────────────────────────────────────────────────

class ChatTurnMetrics:
    """Observes one streamed chat turn from the events it yields.

    The stream decides its path (``turn.path = ...``) and may mark a refusal
    (``turn.outcome = "rate_limited"``); otherwise the outcome follows the
    events: a final ``message`` → ok, an ``error`` event → error, the browser
    going away mid-answer → aborted, an exception → exception.
    """

    __slots__ = ("path", "outcome", "_started")

    def __init__(self) -> None:
        self.path = "agent"
        self.outcome: Optional[str] = None
        self._started = time.perf_counter()

    def see(self, event: dict) -> None:
        if self.outcome is not None:
            return
        kind = event.get("type")
        if kind == "message":
            self.outcome = "ok"
        elif kind == "error":
            self.outcome = "error"

    def finish(self, default_outcome: str) -> None:
        outcome = self.outcome or default_outcome
        CHAT_TURNS.labels(self.path, outcome).inc()
        CHAT_DURATION.labels(self.path, outcome).observe(time.perf_counter() - self._started)


# ── Dependency probes ────────────────────────────────────────────────────────

async def _probe_mongodb() -> None:
    from app.core.database import db

    if db.client is None:
        raise RuntimeError("not connected")
    await db.client.admin.command("ping")


async def _probe_http(url: str, auth=None) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        response = await client.get(url, auth=auth)
        response.raise_for_status()


def _dependency_probes():
    import httpx

    arango_auth = httpx.BasicAuth(settings.ARANGO_USERNAME, settings.ARANGO_PASSWORD)
    return {
        "mongodb": _probe_mongodb,
        "arangodb": lambda: _probe_http(
            f"{settings.ARANGO_URL.rstrip('/')}/_db/{settings.ARANGO_DB_NAME}/_api/version",
            auth=arango_auth,
        ),
        "ollama": lambda: _probe_http(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/version"),
    }


async def _run_probe(name: str, probe) -> None:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_SECONDS)
        up = 1
    except Exception:  # noqa: BLE001 - any failure means "down" for this scrape
        up = 0
    DEPENDENCY_UP.labels(name).set(up)
    DEPENDENCY_PROBE.labels(name).set(time.perf_counter() - started)


async def refresh_dependencies() -> None:
    await asyncio.gather(*(_run_probe(n, p) for n, p in _dependency_probes().items()))


# ── Endpoint ─────────────────────────────────────────────────────────────────

async def metrics_endpoint(request: Request) -> Response:
    """Prometheus scrape target.

    nginx only proxies /api/ and /ws/, so /metrics is not reachable through
    advandeb.com; refusing anything that carries X-Forwarded-For keeps it that
    way should a future proxy rule forward it after all.
    """
    if "x-forwarded-for" in request.headers or "cf-connecting-ip" in request.headers:
        return Response(status_code=404)
    if kb_metrics.AVAILABLE:
        await refresh_dependencies()
    body, content_type, code = kb_metrics.render()
    return Response(content=body, media_type=content_type, status_code=code)
