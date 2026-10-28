#!/usr/bin/env bash
# start_all.sh — DEPRECATED alias for ./scripts/start_stack.sh.
#
# It used to be a second copy of start_stack.sh that never loaded
# app/backend/.env, so every agent it started ran with ARANGO_PASSWORD="".
# Kept only so existing instructions keep working.
echo "[start_all] deprecated: running ./scripts/start_stack.sh" >&2
exec "$(dirname "${BASH_SOURCE[0]}")/start_stack.sh" "$@"
