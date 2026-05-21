#!/usr/bin/env bash
# Restart chatbot_agent in a fully detached process group.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KB_DIR="$REPO_ROOT/knowledge-builder"
PYTHON="$HOME/miniforge3/envs/advandeb/bin/python3"
LOG="$REPO_ROOT/logs/chatbot_agent.log"

pkill -f "advandeb_kb.agents.chatbot_agent" 2>/dev/null
sleep 1

nohup "$PYTHON" -m advandeb_kb.agents.chatbot_agent >> "$LOG" 2>&1 &
echo $! > "$REPO_ROOT/logs/chatbot_agent.pid"
echo "chatbot_agent started PID=$(cat $REPO_ROOT/logs/chatbot_agent.pid)"
