"""
Prometheus metrics shared by the web app and the agent processes.

``prometheus_client`` is an optional dependency. Without it every metric
below is a no-op and :func:`render` reports 503, so a deploy that forgot
``pip install prometheus-client`` still boots — it just isn't observable.

Every process exposes the default registry, which also carries the
``process_*`` collector (RSS, CPU, open fds): that is what the memory alerts
key on, ahead of each unit's systemd MemoryMax.
"""
from __future__ import annotations

import contextlib
from typing import Tuple

try:  # pragma: no cover - exercised by whichever env is installed
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


class _Noop:
    """Stands in for a metric (or a labelled child) when prometheus_client is absent."""

    def labels(self, *args, **kwargs) -> "_Noop":
        return self

    def inc(self, *args, **kwargs) -> None: ...
    def dec(self, *args, **kwargs) -> None: ...
    def set(self, *args, **kwargs) -> None: ...
    def observe(self, *args, **kwargs) -> None: ...
    def set_function(self, *args, **kwargs) -> None: ...
    def set_to_current_time(self, *args, **kwargs) -> None: ...

    def time(self):
        return contextlib.nullcontext()


def counter(name: str, doc: str, labels: Tuple[str, ...] = ()):
    return Counter(name, doc, labels) if AVAILABLE else _Noop()


def gauge(name: str, doc: str, labels: Tuple[str, ...] = ()):
    return Gauge(name, doc, labels) if AVAILABLE else _Noop()


def histogram(name: str, doc: str, labels: Tuple[str, ...] = (), buckets=None):
    if not AVAILABLE:
        return _Noop()
    if buckets is None:
        return Histogram(name, doc, labels)
    return Histogram(name, doc, labels, buckets=buckets)


#: Fast operations (HTTP routes, DB pings). The tail reaches nginx's 300 s
#: proxy timeout so slow uploads and streamed answers land in a real bucket
#: instead of all collapsing into +Inf (the gateway's buckets stopped at 5 s).
HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)
#: LLM-bound work: a chat turn or agent tool call routinely takes 10–120 s.
LLM_BUCKETS = (0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 45, 60, 90, 120, 180, 300, 600)
#: Full-graph artifact rebuilds: seconds to tens of minutes.
REBUILD_BUCKETS = (1, 5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600)


# ── Agent MCP tool calls (advandeb_kb.mcp.protocol.MCPServer) ────────────────
AGENT_TOOL_CALLS = counter(
    "advandeb_agent_tool_calls_total",
    "MCP tool invocations handled by this agent process",
    ("tool", "method", "outcome"),
)
AGENT_TOOL_DURATION = histogram(
    "advandeb_agent_tool_duration_seconds",
    "Wall time of MCP tool invocations handled by this agent process",
    ("tool", "method"),
    buckets=LLM_BUCKETS,
)

# ── Graph artifact rebuild queue (services.graph_rebuild_queue) ──────────────
GRAPH_REBUILD_DIRTY = gauge(
    "advandeb_graph_rebuild_dirty_schemas",
    "Graph schemas marked dirty and waiting for an artifact rebuild",
)
GRAPH_REBUILD_IN_PROGRESS = gauge(
    "advandeb_graph_rebuild_in_progress",
    "1 while a graph artifact rebuild is running",
)
GRAPH_REBUILDS = counter(
    "advandeb_graph_rebuilds_total",
    "Graph artifact rebuilds by schema and outcome",
    ("schema", "outcome"),
)
GRAPH_REBUILD_DURATION = histogram(
    "advandeb_graph_rebuild_duration_seconds",
    "Wall time of one graph artifact rebuild",
    ("schema",),
    buckets=REBUILD_BUCKETS,
)
GRAPH_REBUILD_LAST_SUCCESS = gauge(
    "advandeb_graph_rebuild_last_success_timestamp_seconds",
    "Unix time of the last successful rebuild of each schema",
    ("schema",),
)


def render() -> Tuple[bytes, str, int]:
    """Return (body, content type, HTTP status) for a /metrics response."""
    if not AVAILABLE:
        return (
            b"# prometheus_client is not installed in this environment\n",
            CONTENT_TYPE_LATEST,
            503,
        )
    return generate_latest(), CONTENT_TYPE_LATEST, 200
