#!/usr/bin/env bash
# restart_agent.sh <agent> — restart one agent, e.g. chatbot_agent.
#
# Under systemd this is `systemctl restart advandeb-agent@<agent>.service`,
# so the agent stays inside its unit: supervised, memory-capped, logged to the
# journal. (The old restart_chatbot.sh started it with nohup from your shell —
# outside the stack's cgroup, unsupervised, invisible to systemctl.)
# Without the units (dev mode) it restarts the start_stack.sh-managed process.
#
# Usage: ./scripts/restart_agent.sh chatbot_agent

set -uo pipefail
LOG_TAG=restart_agent
# shellcheck source=lib/stack_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/stack_common.sh"

name="${1:-}"
if ! port=$(agent_port "$name"); then
    echo "usage: $0 <agent>   one of: ${AGENT_NAMES[*]}" >&2
    exit 2
fi

if systemd_stack_active; then
    log "systemd: restarting advandeb-agent@$name.service"
    exec sudo systemctl restart "advandeb-agent@$name.service"
fi

stop_component "$name"
start_component "$name"
if wait_http "http://localhost:$((port + 100))/health" "${AGENT_WAIT_SECS:-180}"; then
    log "$name healthy. If the gateway is in use, re-register: ./scripts/register_all_agents.sh"
else
    log "ERROR: $name did not become healthy — see $LOGS/$name.log"
    exit 1
fi
