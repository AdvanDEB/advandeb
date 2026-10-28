#!/usr/bin/env bash
# stop_stack.sh — stop an agent stack started by ./scripts/start_stack.sh.
#
# Refuses while the stack runs under systemd (use systemctl then): killing a
# supervised agent only makes systemd start it again.
#
# Usage: ./scripts/stop_stack.sh

set -uo pipefail
LOG_TAG=stop_stack
# shellcheck source=lib/stack_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/stack_common.sh"

refuse_if_supervised stop

log "AdvanDEB stack STOP"
for (( i = ${#AGENT_NAMES[@]} - 1; i >= 0; i-- )); do
    stop_component "${AGENT_NAMES[$i]}"
done
stop_component gateway

# Agents started by something other than start_stack.sh (no PID file), e.g.
# the removed restart_chatbot.sh. Only reached when systemd is not running them.
if pkill -f "advandeb_kb.agents" 2>/dev/null; then
    log "  killed agent processes that had no PID file"
fi
log "Stack stopped."
