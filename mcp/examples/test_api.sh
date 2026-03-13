#!/bin/bash
# Example script to test the MCP Gateway REST API
# Usage: ./examples/test_api.sh

set -e

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080}"

echo "MCP Gateway API Test Script"
echo "============================"
echo "Gateway URL: $GATEWAY_URL"
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper function to print section headers
section() {
    echo -e "\n${BLUE}=== $1 ===${NC}"
}

# Helper function to print success
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# 1. Check health
section "1. Health Check"
curl -s "$GATEWAY_URL/health" | jq .
success "Health check passed"

# 2. Register an example agent
section "2. Register Example Agent"
cat <<EOF | curl -s -X POST "$GATEWAY_URL/agents" \
    -H "Content-Type: application/json" \
    -d @- | jq .
{
  "name": "example-agent",
  "websocket_url": "ws://localhost:9001",
  "tools": [
    {
      "name": "echo",
      "description": "Echo back the input",
      "inputSchema": {
        "type": "object",
        "properties": {
          "message": {"type": "string"}
        }
      }
    },
    {
      "name": "calculator",
      "description": "Perform basic calculations",
      "inputSchema": {
        "type": "object",
        "properties": {
          "operation": {"type": "string"},
          "a": {"type": "number"},
          "b": {"type": "number"}
        }
      }
    }
  ]
}
EOF
success "Agent registered"

# 3. List all agents
section "3. List All Agents"
curl -s "$GATEWAY_URL/agents" | jq .
success "Listed all agents"

# 4. Get pool statistics
section "4. Connection Pool Stats"
curl -s "$GATEWAY_URL/pool/stats" | jq .
success "Retrieved pool stats"

# 5. Get Prometheus metrics
section "5. Prometheus Metrics (sample)"
curl -s "$GATEWAY_URL/metrics" | grep -E "^(mcp_|# HELP|# TYPE)" | head -20
success "Metrics endpoint working"

# 6. Update agent status
section "6. Update Agent Status"
curl -s -X PUT "$GATEWAY_URL/agents/example-agent/status" \
    -H "Content-Type: application/json" \
    -d '{"status": "Degraded"}' | jq .
success "Agent status updated"

# 7. List agents again to see status change
section "7. Verify Status Change"
curl -s "$GATEWAY_URL/agents" | jq '.[] | select(.name == "example-agent")'
success "Status change verified"

# 8. Deregister the agent
section "8. Deregister Agent"
curl -s -X DELETE "$GATEWAY_URL/agents/example-agent"
success "Agent deregistered"

# 9. Verify agent is gone
section "9. Verify Agent Removed"
AGENT_COUNT=$(curl -s "$GATEWAY_URL/agents" | jq 'length')
echo "Remaining agents: $AGENT_COUNT"
success "Cleanup complete"

echo ""
echo -e "${GREEN}All tests passed!${NC}"
echo ""
echo "Next steps:"
echo "  - Start a real agent server on ws://localhost:9001"
echo "  - Use examples/client.py to test WebSocket connections"
echo "  - See examples/mock_agent.py for a simple agent implementation"
