"""
MCP Gateway client — WebSocket interface (JSON-RPC 2.0).

All communication with the MCP Gateway uses WebSocket at ws://<host>/mcp.
The gateway exposes no REST endpoint for tool calls — only WebSocket.
The primary tool for user chat queries is `full_pipeline` (query_planner agent),
which orchestrates: plan → semantic_search → synthesize_answer → attribute_citations.
"""
import json
import websockets  # type: ignore
from typing import Dict, Any, AsyncIterator, Optional

from app.core.config import settings


class MCPClient:
    """Client for communicating with the MCP Gateway via WebSocket."""

    def __init__(self, base_url: Optional[str] = None):
        http_url = base_url or settings.MCP_SERVER_URL
        # Always use WebSocket URL — gateway exposes /mcp as WebSocket only
        self.ws_url = http_url.replace("http://", "ws://").replace("https://", "wss://")

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call a tool on the MCP Gateway via WebSocket (JSON-RPC 2.0).

        Returns the ``result`` field of the JSON-RPC response, or raises on error.
        """
        params: Dict[str, Any] = {
            "name": tool_name,
            "arguments": arguments,
        }
        if agent:
            params["agent"] = agent

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": params,
        }

        ws_endpoint = f"{self.ws_url}/mcp"
        try:
            async with websockets.connect(ws_endpoint) as ws:
                await ws.send(json.dumps(payload))
                raw = await ws.recv()
                response = json.loads(raw)
                if "error" in response:
                    raise RuntimeError(
                        f"MCP error {response['error'].get('code')}: "
                        f"{response['error'].get('message')}"
                    )
                return response.get("result", {})
        except (websockets.WebSocketException, OSError) as exc:
            raise RuntimeError(f"MCP Gateway not reachable: {exc}") from exc

    async def stream_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream tool results via WebSocket for real-time agent activity updates.

        For chat queries, ``tool_name`` should be ``"full_pipeline"`` which
        orchestrates the full query_planner → retrieval → synthesis chain.

        Yields event dicts of the form:
          {"type": "agent_activity", "agent": "...", "status": "working", ...}
          {"type": "partial_result", "text": "..."}
          {"type": "final_result", "answer": "...", "citations": [...]}
          {"type": "error", "message": "..."}
        """
        ws_endpoint = f"{self.ws_url}/mcp"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
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
                        response = json.loads(raw)

                        # Handle JSON-RPC error response
                        if "error" in response:
                            yield {
                                "type": "error",
                                "message": response["error"].get("message", "Unknown MCP error"),
                            }
                            break

                        result = response.get("result", {})

                        # If result contains streaming event fields, yield as-is
                        if "type" in result:
                            yield result
                            if result.get("type") in ("final_result", "error"):
                                break
                        else:
                            # Single-shot response — wrap as final_result
                            answer = (
                                result.get("answer")
                                or result.get("text")
                                or result.get("result")
                                or json.dumps(result)
                            )
                            yield {
                                "type": "final_result",
                                "answer": answer,
                                "citations": result.get("citations", []),
                            }
                            break

                    except websockets.ConnectionClosed:
                        break

        except (websockets.WebSocketException, OSError):
            yield {
                "type": "final_result",
                "answer": "MCP Gateway is not reachable.",
                "citations": [],
            }

    async def chat(self, messages: list[Dict[str, str]]) -> Dict[str, str]:
        """Send a chat conversation to MCP via the full_pipeline tool.

        Extracts the last user message and runs it through full_pipeline
        (query_planner → retrieval → synthesis).
        """
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        if not last_user:
            return {"role": "assistant", "content": "No user message provided."}

        try:
            result = await self.call_tool(
                "full_pipeline",
                {"query": last_user, "top_k": 5},
            )
            answer = (
                result.get("answer")
                or result.get("text")
                or result.get("result")
                or "No answer returned."
            )
            return {"role": "assistant", "content": answer}
        except Exception as exc:
            return {
                "role": "assistant",
                "content": f"Sorry, I'm having trouble connecting to the AI service: {exc}",
            }
