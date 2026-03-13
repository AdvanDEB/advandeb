#!/usr/bin/env bash
# start_all.sh — Start MCP Gateway and all 5 specialized agents.
# All services run natively (no Docker). Logs go to logs/
# Usage: ./scripts/start_all.sh
# Stop all: ./scripts/stop_all.sh  (or kill the PIDs in logs/*.pid)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KB_DIR="$REPO_ROOT/knowledge-builder"
MCP_BIN="$REPO_ROOT/mcp/target/release/advandeb-mcp"
MCP_CONFIG="$REPO_ROOT/mcp/config/default.toml"
LOGS="$REPO_ROOT/logs"
CONDA_ENV="advandeb"

mkdir -p "$LOGS"

log() { echo "[start_all] $*"; }

# -----------------------------------------------------------------------
# 1. MCP Gateway (Rust binary)
# -----------------------------------------------------------------------
if [[ ! -f "$MCP_BIN" ]]; then
  log "ERROR: Gateway binary not found at $MCP_BIN"
  log "       Run: cd mcp && cargo build --release"
  exit 1
fi

log "Starting MCP Gateway on :8080..."
"$MCP_BIN" --config "$MCP_CONFIG" \
  > "$LOGS/gateway.log" 2>&1 &
echo $! > "$LOGS/gateway.pid"
log "  Gateway PID $(cat "$LOGS/gateway.pid") — log: $LOGS/gateway.log"

# Give the gateway a moment to bind
sleep 1

# -----------------------------------------------------------------------
# 2. Five specialized agents (Python, conda env advandeb)
# -----------------------------------------------------------------------
declare -A AGENTS=(
  ["retrieval_agent"]="8081"
  ["graph_explorer_agent"]="8082"
  ["synthesis_agent"]="8083"
  ["query_planner_agent"]="8084"
  ["curator_agent"]="8085"
)

for agent_module in "${!AGENTS[@]}"; do
  port="${AGENTS[$agent_module]}"
  log "Starting $agent_module on ws://localhost:$port ..."
  conda run -n "$CONDA_ENV" python -m "advandeb_kb.agents.$agent_module" \
    > "$LOGS/${agent_module}.log" 2>&1 &
  echo $! > "$LOGS/${agent_module}.pid"
  log "  $agent_module PID $(cat "$LOGS/${agent_module}.pid") — log: $LOGS/${agent_module}.log"
done

log ""
log "All services started. Wait a few seconds then run:"
log "  ./scripts/register_all_agents.sh"
log ""
log "To follow logs:"
log "  tail -f $LOGS/gateway.log"
log "  tail -f $LOGS/retrieval_agent.log"
