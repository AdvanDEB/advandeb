#!/usr/bin/env bash
# status_stack.sh — Show the live status of every AdvanDEB stack component.
# Usage: ./scripts/status_stack.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS="$REPO_ROOT/logs"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "  ${GREEN}[UP]${RESET}   $*"; }
fail() { echo -e "  ${RED}[DOWN]${RESET} $*"; }
warn() { echo -e "  ${YELLOW}[WARN]${RESET} $*"; }

check_pid() {
    local name="$1"
    local pidfile="$LOGS/${name}.pid"
    if [[ -f "$pidfile" ]]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
    fi
    echo "?"
    return 1
}

check_http() {
    local url="$1"
    curl -sf "$url" > /dev/null 2>&1
}

echo ""
echo -e "${BOLD}AdvanDEB Stack Status${RESET}  ($(date '+%Y-%m-%d %H:%M:%S'))"
echo "============================================================"

# ---- systemd services -----------------------------------------------
echo ""
echo -e "${BOLD}Systemd services:${RESET}"

for svc in advandeb-stack.service advandeb.service; do
    state=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
    if [[ "$state" == "active" ]]; then
        ok "$svc  ($state)"
    else
        fail "$svc  ($state)"
    fi
done

# ---- MCP Gateway ----------------------------------------------------
echo ""
echo -e "${BOLD}MCP Gateway:${RESET}"
pid=$(check_pid "gateway") && pid_ok=true || pid_ok=false
if $pid_ok && check_http "http://localhost:8080/health"; then
    ok "gateway  PID=$pid  :8080  http://localhost:8080/health"
elif $pid_ok; then
    warn "gateway  PID=$pid  :8080  (process up, HTTP not responding)"
else
    fail "gateway  :8080  (not running)"
fi

# ---- Python Agents --------------------------------------------------
echo ""
echo -e "${BOLD}Python Agents:${RESET}"

declare -A AGENTS=(
    ["retrieval_agent"]="8081"
    ["graph_explorer_agent"]="8082"
    ["synthesis_agent"]="8083"
    ["query_planner_agent"]="8084"
    ["curator_agent"]="8085"
    ["chatbot_agent"]="8086"
)

for agent in retrieval_agent graph_explorer_agent synthesis_agent \
             query_planner_agent curator_agent chatbot_agent; do
    port="${AGENTS[$agent]}"
    health_port=$((port + 100))
    pid=$(check_pid "$agent") && pid_ok=true || pid_ok=false
    if $pid_ok && check_http "http://localhost:${health_port}/health"; then
        ok "$agent  PID=$pid  ws=:$port  health=:$health_port"
    elif $pid_ok; then
        warn "$agent  PID=$pid  ws=:$port  (process up, health not responding)"
    else
        fail "$agent  ws=:$port  (not running)"
    fi
done

# ---- App backend (advandeb.service) ---------------------------------
echo ""
echo -e "${BOLD}App Backend (uvicorn :8400):${RESET}"
if check_http "http://localhost:8400/health"; then
    pid=$(pgrep -f "uvicorn app.main:app" | head -1 || echo "?")
    ok "backend  PID=$pid  :8400  http://localhost:8400/health"
else
    fail "backend  :8400  (not responding)"
fi

# ---- Recent stack log -----------------------------------------------
echo ""
echo -e "${BOLD}Recent stack log  ($LOGS/stack.log):${RESET}"
echo "------------------------------------------------------------"
if [[ -f "$LOGS/stack.log" ]]; then
    tail -20 "$LOGS/stack.log"
else
    echo "  (no stack.log yet)"
fi

echo ""
echo -e "${BOLD}Individual logs:${RESET}  $LOGS/"
for name in gateway retrieval_agent graph_explorer_agent synthesis_agent \
            query_planner_agent curator_agent chatbot_agent; do
    logfile="$LOGS/${name}.log"
    if [[ -f "$logfile" ]]; then
        size=$(du -sh "$logfile" 2>/dev/null | cut -f1)
        echo "  $logfile  ($size)"
    fi
done
echo ""
