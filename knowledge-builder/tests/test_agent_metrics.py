"""Agent /metrics on the health port, and MCP tool-call instrumentation."""
from __future__ import annotations

import asyncio
import json

import pytest

from advandeb_kb import metrics
from advandeb_kb.agents.base_agent import BaseAgent
from advandeb_kb.mcp.protocol import MCPServer


class _Agent(BaseAgent):
    async def initialize(self) -> None: ...
    def register_tools(self) -> None: ...


class _Writer:
    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None: ...
    def close(self) -> None: ...


async def _request(agent: BaseAgent, raw: bytes) -> bytes:
    reader = asyncio.StreamReader()
    reader.feed_data(raw)
    reader.feed_eof()
    writer = _Writer()
    await agent._handle_health(reader, writer)
    return writer.data


async def test_health_still_answers_json():
    response = await _request(_Agent("t", 9999), b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
    head, body = response.split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 200 OK")
    assert json.loads(body) == {"status": "ok", "agent": "t"}


async def test_metrics_path_serves_prometheus_text():
    response = await _request(_Agent("t", 9999), b"GET /metrics HTTP/1.1\r\n\r\n")
    head, body = response.split(b"\r\n\r\n", 1)
    if metrics.AVAILABLE:
        assert head.startswith(b"HTTP/1.1 200 OK")
        assert b"advandeb_agent_tool_calls_total" in body
    else:
        assert head.startswith(b"HTTP/1.1 503")


@pytest.mark.skipif(not metrics.AVAILABLE, reason="prometheus_client not installed")
async def test_tool_calls_are_counted_by_outcome():
    from prometheus_client import REGISTRY

    server = MCPServer()

    async def ok_tool():
        return {"fine": True}

    async def bad_tool():
        raise ValueError("nope")

    server.register_tool("ok_tool", ok_tool)
    server.register_tool("bad_tool", bad_tool)

    def count(tool, outcome):
        return REGISTRY.get_sample_value(
            "advandeb_agent_tool_calls_total", {"tool": tool, "method": "call", "outcome": outcome}
        ) or 0.0

    ok_before, bad_before = count("ok_tool", "ok"), count("bad_tool", "error")
    await server.handle_message(json.dumps({"id": 1, "method": "tools/call", "params": {"name": "ok_tool"}}))
    reply = await server.handle_message(json.dumps({"id": 2, "method": "tools/call", "params": {"name": "bad_tool"}}))
    assert "error" in json.loads(reply)
    assert count("ok_tool", "ok") - ok_before == 1
    assert count("bad_tool", "error") - bad_before == 1
