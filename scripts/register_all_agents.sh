#!/usr/bin/env bash
# register_all_agents.sh — register the six agents with the MCP gateway.
#
# For each agent: wait for its health endpoint, ask it for tools/list over
# WebSocket, POST the tools to the gateway's /agents. Every agent is
# attempted; the exit status is non-zero if ANY registration failed, so the
# caller (advandeb-register-agents.service, start_stack.sh) reports failure
# instead of "started successfully".
#
# The gateway keeps its registry in memory: re-run this after the gateway
# restarts (systemd does it via advandeb-register-agents.service).
#
# Env: ADVANDEB_PYTHON (interpreter), REGISTER_WAIT_SECS (per-agent health wait, default 180)
# Usage: ./scripts/register_all_agents.sh

set -uo pipefail
LOG_TAG=register
# shellcheck source=lib/stack_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/stack_common.sh"

HELPER="$REPO_ROOT/scripts/_register_agent_helper.py"
WAIT_SECS=${REGISTER_WAIT_SECS:-180}

if [[ ! -x "$PYTHON" ]]; then
    log "ERROR: Python interpreter not found: $PYTHON (set ADVANDEB_PYTHON)"
    exit 1
fi

log "Waiting for gateway at $GATEWAY_HTTP/health ..."
if ! wait_http "$GATEWAY_HTTP/health" 30; then
    log "ERROR: gateway did not respond within 30 s"
    exit 1
fi

failed=()
for i in "${!AGENT_NAMES[@]}"; do
    module="${AGENT_NAMES[$i]}" port="${AGENT_PORTS[$i]}" name="${AGENT_GATEWAY_NAMES[$i]}"
    if ! wait_http "http://localhost:$((port + 100))/health" "$WAIT_SECS"; then
        log "FAIL $name: $module not healthy after ${WAIT_SECS} s"
        failed+=("$name")
        continue
    fi
    if "$PYTHON" "$HELPER" "$name" "$port" "$GATEWAY_HTTP"; then
        :
    else
        log "FAIL $name: registration call failed"
        failed+=("$name")
    fi
done

if (( ${#failed[@]} )); then
    log "Registration FAILED for: ${failed[*]}"
    exit 1
fi
log "All ${#AGENT_NAMES[@]} agents registered. Verify: curl -s $GATEWAY_HTTP/agents | python3 -m json.tool"
