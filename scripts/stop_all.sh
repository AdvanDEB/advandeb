#!/usr/bin/env bash
# stop_all.sh — Stop all AdvanDEB services started by start_all.sh.
# Usage: ./scripts/stop_all.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS="$REPO_ROOT/logs"

log() { echo "[stop_all] $*"; }

stop_pid_file() {
  local name="$1"
  local pidfile="$LOGS/${name}.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      log "Stopping $name (PID $pid)..."
      kill "$pid" 2>/dev/null || true
    else
      log "$name (PID $pid) is not running."
    fi
    rm -f "$pidfile"
  else
    log "No PID file for $name — skipping."
  fi
}

stop_pid_file "gateway"
stop_pid_file "retrieval_agent"
stop_pid_file "graph_explorer_agent"
stop_pid_file "synthesis_agent"
stop_pid_file "query_planner_agent"
stop_pid_file "curator_agent"

# Also kill any lingering Python agent processes by module name
pkill -f "advandeb_kb.agents" 2>/dev/null && log "Killed remaining agent processes." || true

log "Done."
