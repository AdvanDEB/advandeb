#!/usr/bin/env bash
# register_all_agents.sh — Register all 5 agents with the MCP Gateway.
#
# For each agent:
#   1. Connect to the agent's WebSocket and send a tools/list MCP call.
#   2. POST the returned tools to the gateway's POST /agents endpoint.
#
# Requires: python3, websockets (conda env advandeb), curl, jq
# Usage: ./scripts/register_all_agents.sh

set -euo pipefail

GATEWAY_HTTP="http://localhost:8080"
CONDA_ENV="advandeb"

log() { echo "[register] $*"; }

# -----------------------------------------------------------------------
# Fetch tools from an agent WebSocket via tools/list MCP call
# -----------------------------------------------------------------------
fetch_and_register() {
  local name="$1"
  local port="$2"

  log "Fetching tools from $name (ws://localhost:$port)..."

  # Use Python to do the WebSocket tools/list call and POST to gateway
  conda run -n "$CONDA_ENV" python3 - "$name" "$port" "$GATEWAY_HTTP" <<'PYEOF'
import sys, json, asyncio
import websockets
import urllib.request

agent_name = sys.argv[1]
port = int(sys.argv[2])
gateway = sys.argv[3]

async def main():
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

    print(f"  [{agent_name}] registered {len(tools)} tools — gateway response {status}: {rdata[:120]}")

asyncio.run(main())
PYEOF
}

# -----------------------------------------------------------------------
# Wait for gateway to be up
# -----------------------------------------------------------------------
log "Waiting for gateway at $GATEWAY_HTTP/health ..."
for i in $(seq 1 20); do
  if curl -sf "$GATEWAY_HTTP/health" > /dev/null 2>&1; then
    log "Gateway is up."
    break
  fi
  sleep 1
  if [[ $i -eq 20 ]]; then
    log "ERROR: Gateway did not respond after 20s. Is it running?"
    exit 1
  fi
done

# -----------------------------------------------------------------------
# Register each agent
# -----------------------------------------------------------------------
fetch_and_register "retrieval_agent"    8081
fetch_and_register "graph_explorer"     8082
fetch_and_register "synthesis_agent"    8083
fetch_and_register "query_planner"      8084
fetch_and_register "curator_agent"      8085

log ""
log "All agents registered. Verify with:"
log "  curl -s $GATEWAY_HTTP/agents | python3 -m json.tool"
