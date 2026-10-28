# shellcheck shell=bash
# stack_common.sh — shared by start_stack.sh, stop_stack.sh, status_stack.sh,
# register_all_agents.sh and restart_agent.sh. Source it; don't run it.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOGS="$REPO_ROOT/logs"
# The conda env's interpreter by absolute path: `conda` is not on systemd's
# PATH, which is why 48 of 50 registrations logged "conda: command not found".
PYTHON="${ADVANDEB_PYTHON:-$HOME/miniforge3/envs/advandeb/bin/python}"
LAUNCHER="$REPO_ROOT/scripts/run_component.py"
# shellcheck disable=SC2034  # used by the scripts that source this file
GATEWAY_HTTP="http://localhost:8080"

# Agent module, WebSocket port (health/metrics on port+100), and the name the
# gateway registers it under. Ordered: start order, and reverse stop order.
AGENT_NAMES=(retrieval_agent graph_explorer_agent synthesis_agent query_planner_agent curator_agent chatbot_agent)
AGENT_PORTS=(8081 8082 8083 8084 8085 8086)
# shellcheck disable=SC2034
AGENT_GATEWAY_NAMES=(retrieval_agent graph_explorer synthesis_agent query_planner curator_agent chatbot_agent)

# Dev-mode log files rotate at start once they pass this size; under systemd
# the components log to the journal, which rotates itself.
LOG_ROTATE_BYTES=$((10 * 1024 * 1024))
LOG_ROTATE_KEEP=5

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [${LOG_TAG:-stack}] $*"; }

agent_port() {
    local i
    for i in "${!AGENT_NAMES[@]}"; do
        [[ "${AGENT_NAMES[$i]}" == "$1" ]] && { echo "${AGENT_PORTS[$i]}"; return 0; }
    done
    return 1
}

# True when the stack is supervised by systemd (new units or the legacy
# advandeb-stack.service). Scripts that start or kill processes by hand
# refuse in that case — two copies would fight over the ports, and pkill
# would only make systemd restart what it just lost.
systemd_stack_active() {
    command -v systemctl >/dev/null 2>&1 || return 1
    systemctl is-active --quiet advandeb-stack.target 2>/dev/null && return 0
    systemctl is-active --quiet advandeb-stack.service 2>/dev/null && return 0
    return 1
}

# True when this script IS the legacy advandeb-stack.service's ExecStart/
# ExecStop (migration window): that unit is then activating/deactivating and
# must not trip the refusal below. Decided by our own cgroup, not by
# INVOCATION_ID, which terminals spawned by systemd user services inherit.
under_legacy_unit() { grep -q '/advandeb-stack\.service$' /proc/self/cgroup 2>/dev/null; }

refuse_if_supervised() {
    if ! under_legacy_unit && systemd_stack_active; then
        log "ERROR: the stack is running under systemd. Use:"
        log "         sudo systemctl ${1:-restart} advandeb-stack.target"
        log "       or for one agent: sudo systemctl ${1:-restart} advandeb-agent@<name>.service"
        exit 2
    fi
}

rotate_log() {
    local file="$1" size i
    [[ -f "$file" ]] || return 0
    size=$(stat -c %s "$file" 2>/dev/null || echo 0)
    (( size < LOG_ROTATE_BYTES )) && return 0
    for (( i = LOG_ROTATE_KEEP - 1; i >= 1; i-- )); do
        [[ -f "$file.$i" ]] && mv -f "$file.$i" "$file.$((i + 1))"
    done
    mv -f "$file" "$file.1"
}

# start_component NAME — launch one component detached, PID in logs/NAME.pid.
start_component() {
    local name="$1" logfile="$LOGS/$1.log"
    mkdir -p "$LOGS"
    rotate_log "$logfile"
    setsid "$PYTHON" "$LAUNCHER" "$name" >> "$logfile" 2>&1 < /dev/null &
    echo $! > "$LOGS/$name.pid"
    log "  $name  PID=$!  log=$logfile"
}

# stop_component NAME — TERM, wait up to 10 s, then KILL.
stop_component() {
    local name="$1" pidfile="$LOGS/$1.pid" pid i
    [[ -f "$pidfile" ]] || { log "  $name: no PID file"; return 0; }
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
        log "  stopping $name (PID $pid)"
        kill "$pid" 2>/dev/null || true
        for (( i = 0; i < 20; i++ )); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.5
        done
        if kill -0 "$pid" 2>/dev/null; then
            log "  $name ignored SIGTERM — SIGKILL"
            kill -9 "$pid" 2>/dev/null || true
        fi
    else
        log "  $name (PID $pid) was not running"
    fi
    rm -f "$pidfile"
}

# wait_http URL SECONDS — 0 once URL answers 2xx, 1 on timeout.
wait_http() {
    local url="$1" secs="$2" i
    for (( i = 1; i <= secs; i++ )); do
        curl -sf -m 2 "$url" > /dev/null 2>&1 && return 0
        sleep 1
    done
    return 1
}
