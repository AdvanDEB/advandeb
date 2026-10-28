#!/usr/bin/env bash
# stop_all.sh — DEPRECATED alias for ./scripts/stop_stack.sh
# (which, unlike the old stop_all.sh, also stops chatbot_agent).
echo "[stop_all] deprecated: running ./scripts/stop_stack.sh" >&2
exec "$(dirname "${BASH_SOURCE[0]}")/stop_stack.sh" "$@"
