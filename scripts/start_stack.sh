#!/usr/bin/env bash
# start_stack.sh — start the AdvanDEB agent stack by hand (development, or a
# host without the systemd units):
#   MCP gateway (:8080) + retrieval, graph_explorer, synthesis, query_planner,
#   curator and chatbot agents (ws :8081–8086, health and /metrics on +100),
#   then registers the agents with the gateway.
#
# Production runs the same components as systemd units — see
# scripts/systemd/README.md — and this script refuses while they are active.
#
# Every component is launched through scripts/run_component.py, the launcher
# the units use, so each gets only the variables it needs from
# app/backend/.env (start_all.sh never loaded the file at all, so its agents
# ran with ARANGO_PASSWORD="").
#
# Logs: logs/<component>.log (rotated at 10 MB, 5 kept). PIDs: logs/<component>.pid
# Exit status: 0 only if every component came up healthy AND registered.
#
# Usage: ./scripts/start_stack.sh            stop: ./scripts/stop_stack.sh

set -uo pipefail
LOG_TAG=start_stack
# shellcheck source=lib/stack_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/stack_common.sh"

refuse_if_supervised restart

log "=========================================================="
log "AdvanDEB stack START  (repo: $REPO_ROOT)"
log "=========================================================="

if [[ ! -x "$PYTHON" ]]; then
    log "ERROR: Python interpreter not found: $PYTHON (set ADVANDEB_PYTHON)"
    exit 1
fi

failures=()

# 1. Gateway. Its failure is reported but does not stop the agents: the web
# app talks to the agents directly and runs without the gateway.
stop_component gateway >/dev/null
log "Starting MCP gateway (:8080)..."
start_component gateway
if wait_http "$GATEWAY_HTTP/health" 20; then
    log "  gateway healthy"
else
    log "  ERROR: gateway did not become healthy within 20 s — see $LOGS/gateway.log"
    failures+=(gateway)
fi

# 2. Agents, all at once; then wait for each (retrieval loads an embedding model).
for name in "${AGENT_NAMES[@]}"; do
    stop_component "$name" >/dev/null
    start_component "$name"
done

WAIT_SECS=${AGENT_WAIT_SECS:-180}
log "Waiting for agents to become healthy (up to ${WAIT_SECS} s each)..."
for name in "${AGENT_NAMES[@]}"; do
    health=$(( $(agent_port "$name") + 100 ))
    if wait_http "http://localhost:$health/health" "$WAIT_SECS"; then
        log "  $name  :$health UP"
    else
        log "  ERROR: $name did not become healthy — see $LOGS/$name.log"
        failures+=("$name")
    fi
done

# 3. Registration (needs the gateway).
if [[ " ${failures[*]} " == *" gateway "* ]]; then
    log "Skipping agent registration: the gateway is down."
    failures+=(registration)
elif ! REGISTER_WAIT_SECS=5 bash "$REPO_ROOT/scripts/register_all_agents.sh"; then
    failures+=(registration)
fi

log "=========================================================="
if (( ${#failures[@]} == 0 )); then
    log "Stack started: gateway + ${#AGENT_NAMES[@]} agents healthy and registered."
    exit 0
fi
log "Stack started WITH FAILURES: ${failures[*]}"
log "Running components keep running; fix the failures and re-run, or stop with ./scripts/stop_stack.sh"
exit 1
