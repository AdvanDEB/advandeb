"""
MCP Gateway client — HTTP and WebSocket interfaces.
"""
import json
import httpx
from typing import Dict, Any, AsyncIterator, Optional

from app.core.config import settings


class MCPClient:
    """Client for communicating with the MCP Gateway."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or settings.MCP_SERVER_URL
        # Derive WebSocket URL from HTTP URL
        self.ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call a tool on the MCP Gateway via HTTP POST."""
        payload: Dict[str, Any] = {
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        if agent:
            payload["params"]["agent"] = agent

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/mcp",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def stream_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream tool results via WebSocket for real-time agent activity updates.

        Yields event dicts of the form:
          {"type": "agent_activity", "agent": "...", "status": "working", ...}
          {"type": "partial_result", "text": "..."}
          {"type": "final_result", "answer": "...", "citations": [...]}
        """
        try:
            import websockets  # type: ignore
        except ImportError:
            # Fallback to HTTP if websockets package not installed
            result = await self.call_tool(tool_name, arguments)
            yield {"type": "final_result", **result}
            return

        ws_endpoint = f"{self.ws_url}/mcp"
        payload = {
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        try:
            async with websockets.connect(ws_endpoint) as ws:
                await ws.send(json.dumps(payload))
                while True:
                    try:
                        raw = await ws.recv()
                        event = json.loads(raw)
                        yield event
                        # Stop streaming when final result arrives
                        if event.get("type") in ("final_result", "error"):
                            break
                    except websockets.ConnectionClosed:
                        break
        except Exception:
            # MCP gateway not available — yield a placeholder
            yield {
                "type": "final_result",
                "answer": "MCP Gateway is not reachable.",
                "citations": [],
            }

    async def chat(self, messages: list[Dict[str, str]]) -> Dict[str, Any]:
        """Send a chat conversation to MCP and return the assistant reply."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat",
                    json={"messages": messages},
                    timeout=30.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    return {"role": "assistant", "content": data.get("reply", "")}
        except Exception as exc:
            print(f"MCPClient.chat error: {exc}")

        return {
            "role": "assistant",
            "content": "Sorry, I'm having trouble connecting to the AI service.",
        }
