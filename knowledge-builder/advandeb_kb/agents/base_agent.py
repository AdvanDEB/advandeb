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
import logging
from abc import ABC, abstractmethod

from advandeb_kb.mcp.protocol import MCPClient, MCPServer

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base for advandeb_kb specialized agents.

    Each agent is a self-contained process that:
      - Exposes tools via an MCP WebSocket server
      - Can call other agents via MCPClient

    Args:
        name:         Human-readable agent identifier (used in logging).
        port:         WebSocket port to listen on.
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
        """Initialize, register tools, then start the WebSocket server."""
        logger.info("Agent '%s' initializing on ws://%s:%d", self.name, self.host, self.port)
        await self.initialize()
        self.register_tools()
        logger.info(
            "Agent '%s' ready — tools: %s", self.name, self.server.tool_names
        )
        await self.server.start()

    def run(self) -> None:
        """Convenience: run the agent synchronously (entry point for scripts)."""
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            logger.info("Agent '%s' stopped.", self.name)
