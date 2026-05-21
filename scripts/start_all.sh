#!/usr/bin/env bash
# start_all.sh — Start MCP Gateway and all 6 specialized agents.
# All services run natively. Logs go to logs/
# Usage: ./scripts/start_all.sh
# Stop all: ./scripts/stop_all.sh  (or kill the PIDs in logs/*.pid)

set -uo pipefail   # -e intentionally removed: agent registration failures must not kill the script

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KB_DIR="$REPO_ROOT/knowledge-builder"
MCP_DIR="$REPO_ROOT/mcp"
MCP_BIN="$MCP_DIR/target/release/advandeb-mcp"
LOGS="$REPO_ROOT/logs"
CONDA_ENV="advandeb"
PYTHON="$HOME/miniforge3/envs/$CONDA_ENV/bin/python3"

mkdir -p "$LOGS"

log() { echo "[start_all] $*"; }

# -----------------------------------------------------------------------
# 1. MCP Gateway (Rust binary — must run from mcp/ so config/default.toml
#    is found relative to CWD)
# -----------------------------------------------------------------------
if [[ ! -f "$MCP_BIN" ]]; then
  log "ERROR: Gateway binary not found at $MCP_BIN"
  log "       Run: cd mcp && cargo build --release"
  exit 1
fi

log "Starting MCP Gateway on :8080..."
(cd "$MCP_DIR" && "$MCP_BIN") \
  > "$LOGS/gateway.log" 2>&1 &
echo $! > "$LOGS/gateway.pid"
log "  Gateway PID $(cat "$LOGS/gateway.pid") — log: $LOGS/gateway.log"

# Wait for gateway to be ready
for i in $(seq 1 15); do
  if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    log "  Gateway is ready."
    break
  fi
  sleep 1
  if [[ $i -eq 15 ]]; then
    log "ERROR: Gateway did not respond after 15s."
    exit 1
  fi
done

# -----------------------------------------------------------------------
# 2. Six specialized agents (Python, conda env advandeb)
# Launch all in background; wait for each health endpoint individually.
# -----------------------------------------------------------------------
declare -A AGENTS=(
  ["retrieval_agent"]="8081"
  ["graph_explorer_agent"]="8082"
  ["synthesis_agent"]="8083"
  ["query_planner_agent"]="8084"
  ["curator_agent"]="8085"
  ["chatbot_agent"]="8086"
)

for agent_module in "${!AGENTS[@]}"; do
  port="${AGENTS[$agent_module]}"
  log "Starting $agent_module on ws://localhost:$port ..."
  setsid bash -c "cd '$KB_DIR' && exec '$PYTHON' -m 'advandeb_kb.agents.$agent_module'" \
    >> "$LOGS/${agent_module}.log" 2>&1 &
  echo $! > "$LOGS/${agent_module}.pid"
  log "  $agent_module PID $(cat "$LOGS/${agent_module}.pid") — log: $LOGS/${agent_module}.log"
done

# -----------------------------------------------------------------------
# 3. Wait for each agent's HTTP health endpoint (port + 100)
#    retrieval_agent loads an embedding model — can take up to 90s.
# -----------------------------------------------------------------------
AGENT_WAIT_SECS=120

log ""
log "Waiting for all agents to become healthy (up to ${AGENT_WAIT_SECS}s each)..."

all_ok=true
for agent_module in "${!AGENTS[@]}"; do
  port="${AGENTS[$agent_module]}"
  health_port=$((port + 100))
  ready=false
  for i in $(seq 1 $AGENT_WAIT_SECS); do
    if curl -sf "http://localhost:${health_port}/health" > /dev/null 2>&1; then
      log "  $agent_module :${health_port} — UP (${i}s)"
      ready=true
      break
    fi
    sleep 1
  done
  if [[ "$ready" == "false" ]]; then
    log "  WARNING: $agent_module did not become healthy within ${AGENT_WAIT_SECS}s"
    all_ok=false
  fi
done

# -----------------------------------------------------------------------
# 4. Register agents with the gateway
# -----------------------------------------------------------------------
log ""
log "Registering agents with the MCP gateway..."
bash "$REPO_ROOT/scripts/register_all_agents.sh" || log "WARNING: Some agents failed to register — check logs above."

log ""
if [[ "$all_ok" == "true" ]]; then
  log "All 6 agents started and registered successfully."
else
  log "WARNING: One or more agents may not be ready — check logs in $LOGS/"
fi
log ""
log "Service URLs:"
log "  MCP Gateway       http://localhost:8080/health"
log "  MCP Agents list   http://localhost:8080/agents"
log "  App backend       http://localhost:8400/health  (start separately)"
log "  App frontend      http://localhost:5173          (start separately)"
log ""
log "To follow logs:"
log "  tail -f $LOGS/gateway.log"
log "  tail -f $LOGS/retrieval_agent.log"
log "  tail -f $LOGS/chatbot_agent.log"
log ""
log "To stop all: ./scripts/stop_all.sh"
