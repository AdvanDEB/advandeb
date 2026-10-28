#!/usr/bin/env bash
# status_stack.sh — live status of every AdvanDEB component: systemd units
# (when installed), health endpoints, and where the logs are.
# Read-only. Usage: ./scripts/status_stack.sh

set -uo pipefail
# shellcheck source=lib/stack_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/stack_common.sh"

GREEN='\033[0;32m' RED='\033[0;31m' YELLOW='\033[1;33m' BOLD='\033[1m' RESET='\033[0m'
[[ -t 1 ]] || { GREEN='' RED='' YELLOW='' BOLD='' RESET=''; }
ok()   { echo -e "  ${GREEN}[UP]${RESET}   $*"; }
fail() { echo -e "  ${RED}[DOWN]${RESET} $*"; }
warn() { echo -e "  ${YELLOW}[WARN]${RESET} $*"; }

check_http() { curl -sf -m 3 "$1" > /dev/null 2>&1; }

echo
echo -e "${BOLD}AdvanDEB status${RESET}  ($(date '+%Y-%m-%d %H:%M:%S'))"
echo "============================================================"

echo
echo -e "${BOLD}systemd units:${RESET}"
units=(advandeb.target advandeb.service advandeb-stack.target advandeb-gateway.service)
for name in "${AGENT_NAMES[@]}"; do units+=("advandeb-agent@$name.service"); done
units+=(advandeb-register-agents.service advandeb-stack.service)
for unit in "${units[@]}"; do
    load=$(systemctl show -p LoadState --value "$unit" 2>/dev/null)
    [[ "$load" == "loaded" ]] || continue
    state=$(systemctl is-active "$unit" 2>/dev/null)
    restarts=$(systemctl show -p NRestarts --value "$unit" 2>/dev/null)
    mem=$(systemctl show -p MemoryCurrent --value "$unit" 2>/dev/null)
    extra=""
    [[ -n "$restarts" && "$restarts" != "0" ]] && extra+="  restarts=$restarts"
    [[ "$mem" =~ ^[0-9]+$ ]] && extra+="  mem=$(( mem / 1024 / 1024 ))MiB"
    case "$state" in
        active)     ok   "$unit$extra" ;;
        activating|reloading) warn "$unit ($state)$extra" ;;
        *)          fail "$unit ($state)$extra" ;;
    esac
done
if systemctl show -p LoadState --value advandeb-stack.service 2>/dev/null | grep -qx loaded \
   && systemctl show -p LoadState --value advandeb-stack.target 2>/dev/null | grep -qx loaded; then
    warn "both the legacy advandeb-stack.service and the new advandeb-stack.target are installed — see scripts/systemd/README.md"
fi

echo
echo -e "${BOLD}Endpoints:${RESET}"
if check_http "$GATEWAY_HTTP/health"; then ok "gateway  :8080"; else fail "gateway  :8080"; fi
for i in "${!AGENT_NAMES[@]}"; do
    health=$(( AGENT_PORTS[i] + 100 ))
    if check_http "http://localhost:$health/health"; then
        ok "${AGENT_NAMES[$i]}  ws=:${AGENT_PORTS[$i]}  health=:$health"
    else
        fail "${AGENT_NAMES[$i]}  ws=:${AGENT_PORTS[$i]}  health=:$health"
    fi
done
if check_http "http://localhost:8400/api/health"; then ok "web app  :8400"; else fail "web app  :8400"; fi
if check_http "http://localhost:8400/metrics"; then ok "web app  :8400/metrics"; else warn "web app  :8400/metrics (prometheus-client installed?)"; fi

echo
echo -e "${BOLD}Logs:${RESET}"
echo "  systemd:  journalctl -u advandeb.service -f"
echo "            journalctl -u 'advandeb-agent@*' -u advandeb-gateway.service -f"
echo "            journalctl -u advandeb-agent@chatbot_agent.service --since -1h"
echo "  web app:  $REPO_ROOT/app/backend/logs/app.log (rotated by the app)"
shopt -s nullglob
dev_logs=("$LOGS"/*.log)
if (( ${#dev_logs[@]} )); then
    echo "  dev mode (start_stack.sh): $LOGS/  — $(du -sh "$LOGS" 2>/dev/null | cut -f1) total"
fi
echo
