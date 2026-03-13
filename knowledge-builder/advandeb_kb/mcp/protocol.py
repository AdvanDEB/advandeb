"""
MCP (Model Context Protocol) WebSocket server and client.

Message format (JSON):
    Request:  {"id": "...", "method": "tools/call",  "params": {"name": "...", "arguments": {...}}}
    Response: {"id": "...", "result": {...}}
              {"id": "...", "error":  {"code": -32000, "message": "..."}}

Supported methods:
    tools/list   — returns list of registered tool definitions
    tools/call   — calls a registered tool by name
    ping         — health check
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definition (what agents advertise to callers)
# ---------------------------------------------------------------------------

class ToolDefinition:
    """Metadata for one MCP tool."""

    __slots__ = ("name", "description", "input_schema", "handler")

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable,
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


# ---------------------------------------------------------------------------
# MCPServer
# ---------------------------------------------------------------------------

class MCPServer:
    """
    WebSocket-based MCP tool server.

    Usage:
        server = MCPServer(host="localhost", port=8081)
        server.register_tool("my_tool", description="...", schema={...}, handler=my_fn)
        await server.start()

    Each tool handler may be sync or async; both are supported.
    """

    def __init__(self, host: str = "localhost", port: int = 8081):
        self.host = host
        self.port = port
        self._tools: dict[str, ToolDefinition] = {}

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def register_tool(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        input_schema: Optional[dict] = None,
    ) -> None:
        """Register a tool with its handler function."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema or {"type": "object", "properties": {}},
            handler=handler,
        )
        logger.debug("MCPServer: registered tool '%s'", name)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def handle_message(self, raw: str) -> str:
        """Parse and dispatch one incoming JSON message; return JSON response."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._error(None, -32700, f"Parse error: {exc}")

        msg_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        try:
            if method == "ping":
                result = {"pong": True}

            elif method == "tools/list":
                result = {"tools": [t.to_dict() for t in self._tools.values()]}

            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                if not tool_name:
                    return self._error(msg_id, -32602, "Missing params.name")
                if tool_name not in self._tools:
                    return self._error(msg_id, -32601, f"Unknown tool: {tool_name}")

                tool = self._tools[tool_name]
                if asyncio.iscoroutinefunction(tool.handler):
                    result = await tool.handler(**arguments)
                else:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None, lambda: tool.handler(**arguments)
                    )

            else:
                return self._error(msg_id, -32601, f"Unknown method: {method}")

        except TypeError as exc:
            return self._error(msg_id, -32602, f"Invalid arguments: {exc}")
        except Exception as exc:
            logger.exception("Tool '%s' raised an error: %s", method, exc)
            return self._error(msg_id, -32000, str(exc))

        return json.dumps({"id": msg_id, "result": result})

    # ------------------------------------------------------------------
    # WebSocket server lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the WebSocket server (runs indefinitely)."""
        try:
            import websockets
        except ImportError:
            raise RuntimeError("websockets package required: pip install websockets")

        logger.info(
            "MCPServer starting on ws://%s:%d  tools=%s",
            self.host,
            self.port,
            self.tool_names,
        )

        async def _handler(websocket):
            async for message in websocket:
                response = await self.handle_message(message)
                await websocket.send(response)

        async with websockets.serve(_handler, self.host, self.port):
            await asyncio.Future()  # run forever

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> str:
        return json.dumps({"id": msg_id, "error": {"code": code, "message": message}})


# ---------------------------------------------------------------------------
# MCPClient
# ---------------------------------------------------------------------------

class MCPClient:
    """
    Async WebSocket client for calling tools on MCP agent servers.

    Usage:
        client = MCPClient("ws://localhost:8081")
        result = await client.call_tool("hybrid_search", {"query": "DEB theory"})
    """

    def __init__(self, url: str):
        self.url = url

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call a named tool on the remote agent and return the result."""
        try:
            import websockets
        except ImportError:
            raise RuntimeError("websockets package required: pip install websockets")

        message = json.dumps({
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })

        async with websockets.connect(self.url) as ws:
            await ws.send(message)
            raw = await ws.recv()

        response = json.loads(raw)
        if "error" in response:
            raise RuntimeError(
                f"MCP error {response['error']['code']}: {response['error']['message']}"
            )
        return response.get("result")

    async def list_tools(self) -> list[dict]:
        """Fetch the tool catalog from the remote agent."""
        try:
            import websockets
        except ImportError:
            raise RuntimeError("websockets package required: pip install websockets")

        message = json.dumps({"id": str(uuid.uuid4()), "method": "tools/list"})
        async with websockets.connect(self.url) as ws:
            await ws.send(message)
            raw = await ws.recv()

        response = json.loads(raw)
        return response.get("result", {}).get("tools", [])

    async def ping(self) -> bool:
        """Return True if the agent is reachable."""
        try:
            import websockets
        except ImportError:
            return False
        try:
            message = json.dumps({"id": "ping", "method": "ping"})
            async with websockets.connect(self.url, open_timeout=3) as ws:
                await ws.send(message)
                await ws.recv()
            return True
        except Exception:
            return False
