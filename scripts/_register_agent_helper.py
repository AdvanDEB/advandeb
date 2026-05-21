"""
_register_agent_helper.py — called by register_all_agents.sh
Usage: python3 _register_agent_helper.py <agent_name> <ws_port> <gateway_http>
"""
import sys
import json
import asyncio
import urllib.request
import websockets  # type: ignore

agent_name = sys.argv[1]
port = int(sys.argv[2])
gateway = sys.argv[3]


async def main() -> None:
    uri = f"ws://localhost:{port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}))
        raw = await ws.recv()
        resp = json.loads(raw)

    # Handle both {result: {tools: [...]}} and {tools: [...]}
    result = resp.get("result", resp)
    tools = result.get("tools", [])

    payload = {
        "name": agent_name,
        "websocket_url": f"ws://localhost:{port}",
        "tools": tools,
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{gateway}/agents",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        status = r.status
        rdata = r.read().decode()

    print(f"  [{agent_name}] registered {len(tools)} tools — gateway {status}: {rdata[:120]}")


asyncio.run(main())
