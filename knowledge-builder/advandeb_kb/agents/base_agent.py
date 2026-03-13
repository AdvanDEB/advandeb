"""
BaseAgent — abstract base class for all specialized MCP agent servers.

Subclasses must implement:
    initialize()      — set up DB connections, load models, etc.
    register_tools()  — call self.server.register_tool(...) for each tool

Lifecycle:
    agent = MyAgent()
    await agent.start()   # blocks; ctrl-c to stop
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod

from advandeb_kb.mcp.protocol import MCPClient, MCPServer

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base for advandeb_kb specialized agents.

    Each agent is a self-contained process that:
      - Exposes tools via an MCP WebSocket server
      - Exposes a tiny HTTP /health endpoint (for gateway health checks)
      - Can call other agents via MCPClient

    Args:
        name:         Human-readable agent identifier (used in logging).
        port:         WebSocket port to listen on. HTTP health is at port+100.
        host:         Bind address (default localhost).
        gateway_url:  Optional MCP gateway URL for inter-agent calls.
    """

    def __init__(
        self,
        name: str,
        port: int,
        host: str = "localhost",
        gateway_url: str = "ws://localhost:8080/mcp",
    ):
        self.name = name
        self.port = port
        self.host = host
        self.gateway_url = gateway_url

        self.server = MCPServer(host=host, port=port)
        self._gateway_client = MCPClient(gateway_url)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize resources: DB connections, embedding models, etc."""
        ...

    @abstractmethod
    def register_tools(self) -> None:
        """Register all agent tools with self.server."""
        ...

    # ------------------------------------------------------------------
    # HTTP health endpoint (port + 100)
    # ------------------------------------------------------------------

    async def _handle_health(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Respond to any HTTP request with 200 OK JSON health payload."""
        try:
            await reader.read(1024)  # consume request bytes
        except Exception:
            pass
        body = json.dumps({"status": "ok", "agent": self.name}).encode()
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Connection: close\r\n"
            + b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            + b"\r\n"
            + body
        )
        try:
            writer.write(response)
            await writer.drain()
        finally:
            writer.close()

    async def _start_health_server(self) -> None:
        health_port = self.port + 100
        server = await asyncio.start_server(
            self._handle_health, self.host, health_port
        )
        logger.info(
            "Agent '%s' HTTP health server on http://%s:%d/health",
            self.name, self.host, health_port,
        )
        async with server:
            await server.serve_forever()

    # ------------------------------------------------------------------
    # Inter-agent calls via MCP gateway
    # ------------------------------------------------------------------

    async def call_agent(
        self, agent_name: str, tool_name: str, arguments: dict
    ):
        """
        Call a tool on another agent via the MCP gateway.

        The gateway must be running and have the target agent registered.
        """
        return await self._gateway_client.call_tool(
            tool_name=f"{agent_name}/{tool_name}",
            arguments=arguments,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize, register tools, then start the WebSocket server + health endpoint."""
        logger.info("Agent '%s' initializing on ws://%s:%d", self.name, self.host, self.port)
        await self.initialize()
        self.register_tools()
        logger.info(
            "Agent '%s' ready — tools: %s", self.name, self.server.tool_names
        )
        # Run WebSocket MCP server and HTTP health server concurrently
        await asyncio.gather(
            self.server.start(),
            self._start_health_server(),
        )

    def run(self) -> None:
        """Convenience: run the agent synchronously (entry point for scripts)."""
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            logger.info("Agent '%s' stopped.", self.name)
