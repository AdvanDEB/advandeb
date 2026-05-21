#!/usr/bin/env bash
# stop_stack.sh — Stop all AdvanDEB background stack processes.
# Called by advandeb-stack.service (ExecStop).
# Usage: ./scripts/stop_stack.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS="$REPO_ROOT/logs"
STACK_LOG="$LOGS/stack.log"

log() {
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] [stop_stack] $*"
}

log "=========================================================="
log "AdvanDEB stack STOP"
log "=========================================================="

stop_pid_file() {
    local name="$1"
    local pidfile="$LOGS/${name}.pid"
    if [[ -f "$pidfile" ]]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            log "  Stopping $name (PID $pid)..."
            kill "$pid" 2>/dev/null || true
        else
            log "  $name (PID $pid) already stopped."
        fi
        rm -f "$pidfile"
    else
        log "  No PID file for $name — skipping."
    fi
}

# Stop agents first, then the gateway
stop_pid_file "chatbot_agent"
stop_pid_file "curator_agent"
stop_pid_file "query_planner_agent"
stop_pid_file "synthesis_agent"
stop_pid_file "graph_explorer_agent"
stop_pid_file "retrieval_agent"
stop_pid_file "gateway"

# Kill any lingering agent processes by module name (safety net)
if pkill -f "advandeb_kb.agents" 2>/dev/null; then
    log "  Killed remaining agent processes."
fi

log "Stack stopped."
log "=========================================================="
