"""
_register_agent_helper.py — called by register_all_agents.sh
Usage: python _register_agent_helper.py <agent_name> <ws_port> <gateway_http>

Exits non-zero on any failure (agent unreachable, gateway refused), with
timeouts on every step so a wedged agent cannot hang the caller.
"""
import asyncio
import json
import sys
import urllib.request

import websockets  # type: ignore

agent_name = sys.argv[1]
port = int(sys.argv[2])
gateway = sys.argv[3]

TIMEOUT_SECONDS = 15


async def fetch_tools() -> list:
    uri = f"ws://localhost:{port}"
    async with websockets.connect(uri, open_timeout=TIMEOUT_SECONDS) as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}))
        raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT_SECONDS)
    resp = json.loads(raw)
    # Handle both {result: {tools: [...]}} and {tools: [...]}
    result = resp.get("result", resp)
    return result.get("tools", [])


def main() -> None:
    tools = asyncio.run(fetch_tools())
    payload = {
        "name": agent_name,
        "websocket_url": f"ws://localhost:{port}",
        "tools": tools,
    }
    req = urllib.request.Request(
        f"{gateway}/agents",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
        status = r.status
        rdata = r.read().decode()
    print(f"  [{agent_name}] registered {len(tools)} tools — gateway {status}: {rdata[:120]}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - reported, then a non-zero exit
        print(f"  [{agent_name}] registration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
