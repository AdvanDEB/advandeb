#!/usr/bin/env bash
# start_stack.sh — Start the full AdvanDEB background stack:
#   1. MCP Gateway       (Rust binary, :8080)
#   2. retrieval_agent   (Python, ws :8081, health :8181)
#   3. graph_explorer    (Python, ws :8082, health :8182)
#   4. synthesis_agent   (Python, ws :8083, health :8183)
#   5. query_planner     (Python, ws :8084, health :8184)
#   6. curator_agent     (Python, ws :8085, health :8185)
#   7. chatbot_agent     (Python, ws :8086, health :8186)
#   8. Register all agents with the gateway
#
# All stdout/stderr goes to logs/<component>.log
# PIDs are written to logs/<component>.pid
# A master run-log is written to logs/stack.log
#
# Called by advandeb-stack.service (ExecStart).
# Usage: ./scripts/start_stack.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load environment variables from the app .env so that all agents
# (including graph_explorer_agent) receive ARANGO_PASSWORD, MONGODB_URI, etc.
ENV_FILE="$REPO_ROOT/app/backend/.env"
if [[ -f "$ENV_FILE" ]]; then
    # Export only KEY=VALUE lines, skip comments and blank lines
    set -o allexport
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +o allexport
fi

KB_DIR="$REPO_ROOT/knowledge-builder"
MCP_DIR="$REPO_ROOT/mcp"
MCP_BIN="$MCP_DIR/target/release/advandeb-mcp"
LOGS="$REPO_ROOT/logs"
PYTHON="$HOME/miniforge3/envs/advandeb/bin/python3"
STACK_LOG="$LOGS/stack.log"

mkdir -p "$LOGS"

# ------------------------------------------------------------------
# Logging — every message goes to both stdout and stack.log
# ------------------------------------------------------------------
log() {
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] [start_stack] $*"
}

log "=========================================================="
log "AdvanDEB stack START"
log "REPO_ROOT : $REPO_ROOT"
log "PYTHON    : $PYTHON"
log "=========================================================="

# ------------------------------------------------------------------
# Helper: kill any stale process recorded in a PID file
# ------------------------------------------------------------------
kill_stale() {
    local name="$1"
    local pidfile="$LOGS/${name}.pid"
    if [[ -f "$pidfile" ]]; then
        local old_pid
        old_pid=$(cat "$pidfile")
        if kill -0 "$old_pid" 2>/dev/null; then
            log "  Killing stale $name (PID $old_pid)..."
            kill "$old_pid" 2>/dev/null || true
            sleep 1
        fi
        rm -f "$pidfile"
    fi
}

# ------------------------------------------------------------------
# 1. MCP Gateway
# ------------------------------------------------------------------
if [[ ! -f "$MCP_BIN" ]]; then
    log "ERROR: MCP gateway binary not found at $MCP_BIN"
    log "       Run: cd mcp && cargo build --release"
    exit 1
fi

kill_stale "gateway"
log "Starting MCP Gateway (:8080)..."
(cd "$MCP_DIR" && "$MCP_BIN") >> "$LOGS/gateway.log" 2>&1 &
echo $! > "$LOGS/gateway.pid"
log "  gateway  PID=$(cat "$LOGS/gateway.pid")  log=$LOGS/gateway.log"

# Wait for gateway
for i in $(seq 1 20); do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        log "  gateway ready after ${i}s"
        break
    fi
    sleep 1
    if [[ $i -eq 20 ]]; then
        log "ERROR: Gateway did not respond after 20s — aborting."
        exit 1
    fi
done

# ------------------------------------------------------------------
# 2. Six Python agents
# ------------------------------------------------------------------
declare -A AGENTS=(
    ["retrieval_agent"]="8081"
    ["graph_explorer_agent"]="8082"
    ["synthesis_agent"]="8083"
    ["query_planner_agent"]="8084"
    ["curator_agent"]="8085"
    ["chatbot_agent"]="8086"
)

for agent in "${!AGENTS[@]}"; do
    port="${AGENTS[$agent]}"
    kill_stale "$agent"
    log "Starting $agent (ws :$port, health :$((port+100)))..."
    setsid bash -c "cd '$KB_DIR' && exec '$PYTHON' -m 'advandeb_kb.agents.$agent'" \
        >> "$LOGS/${agent}.log" 2>&1 &
    echo $! > "$LOGS/${agent}.pid"
    log "  $agent  PID=$(cat "$LOGS/${agent}.pid")  log=$LOGS/${agent}.log"
done

# ------------------------------------------------------------------
# 3. Wait for each agent's health endpoint
#    retrieval_agent loads an embedding model — allow up to 120s
# ------------------------------------------------------------------
WAIT_SECS=120
log ""
log "Waiting for all agents to become healthy (up to ${WAIT_SECS}s each)..."

all_ok=true
for agent in "${!AGENTS[@]}"; do
    port="${AGENTS[$agent]}"
    health_port=$((port + 100))
    ready=false
    for i in $(seq 1 $WAIT_SECS); do
        if curl -sf "http://localhost:${health_port}/health" > /dev/null 2>&1; then
            log "  $agent  :${health_port} UP  (${i}s)"
            ready=true
            break
        fi
        sleep 1
    done
    if [[ "$ready" == "false" ]]; then
        log "  WARNING: $agent did not become healthy within ${WAIT_SECS}s"
        all_ok=false
    fi
done

# ------------------------------------------------------------------
# 4. Register agents with the gateway
# ------------------------------------------------------------------
log ""
log "Registering agents with MCP gateway..."
bash "$REPO_ROOT/scripts/register_all_agents.sh" \
    || log "WARNING: Some agents failed to register — check stack.log"

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
log ""
log "=========================================================="
if [[ "$all_ok" == "true" ]]; then
    log "Stack started successfully."
else
    log "Stack started with warnings — check logs above."
fi
log ""
log "Component               Port    PID       Log"
log "----------------------  ------  --------  ----------------------------------"
for f in gateway retrieval_agent graph_explorer_agent synthesis_agent \
          query_planner_agent curator_agent chatbot_agent; do
    pid="$(cat "$LOGS/${f}.pid" 2>/dev/null || echo '?')"
    log "  $f  -  PID=$pid  $LOGS/${f}.log"
done
log ""
log "MCP Gateway health : http://localhost:8080/health"
log "App backend        : http://localhost:8400/health  (advandeb.service)"
log "Stack log          : $STACK_LOG"
log "=========================================================="
