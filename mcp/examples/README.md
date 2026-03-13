# MCP Gateway Examples

This directory contains example scripts and tools for testing and interacting with the MCP Gateway.

## Files

### `mock_agent.py`
A simple MCP agent implementation that can be used for testing the gateway. It provides three tools:
- **echo**: Echo back input messages
- **calculator**: Perform basic arithmetic operations
- **random**: Generate random numbers

**Usage:**
```bash
# Install dependencies
pip install websockets

# Start the mock agent
python examples/mock_agent.py

# Or on a custom port
python examples/mock_agent.py --port 9002 --name my-agent
```

### `client.py`
A Python WebSocket client for interacting with the MCP Gateway. Demonstrates:
- Connecting to the gateway
- Initializing MCP session
- Listing available tools
- Calling tools
- Running workflows

**Usage:**
```bash
# Install dependencies
pip install websockets

# Run basic demo
python examples/client.py

# Run workflow demo
python examples/client.py workflow
```

### `test_api.sh`
A bash script that tests all REST API endpoints of the gateway. Includes:
- Health check
- Agent registration/deregistration
- Status updates
- Pool statistics
- Metrics endpoint

**Usage:**
```bash
# Make sure jq is installed (for JSON formatting)
# Ubuntu/Debian: apt install jq
# macOS: brew install jq

# Run the tests
./examples/test_api.sh

# Or against a different gateway
GATEWAY_URL=http://gateway.example.com ./examples/test_api.sh
```

## Complete Testing Workflow

### 1. Start the MCP Gateway

```bash
cd mcp
cargo run
```

The gateway will start on `http://localhost:8080`.

### 2. Start a Mock Agent

In another terminal:

```bash
python examples/mock_agent.py
```

The agent will start on `ws://localhost:9001` and display registration command.

### 3. Register the Agent

Use the curl command shown by the mock agent, or:

```bash
curl -X POST http://localhost:8080/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mock-agent",
    "websocket_url": "ws://localhost:9001",
    "tools": [
      {
        "name": "echo",
        "description": "Echo back the input message",
        "inputSchema": {
          "type": "object",
          "properties": {
            "message": {"type": "string"}
          }
        }
      }
    ]
  }'
```

### 4. Test with the Client

In another terminal:

```bash
python examples/client.py
```

You should see:
1. Connection established
2. Session initialized
3. Tools listed (including the mock agent's tools)
4. A tool call executed

### 5. Test the REST API

```bash
./examples/test_api.sh
```

This will test all REST endpoints and verify the gateway is working correctly.

## Expected Output

### Mock Agent
```
Starting mock-agent on ws://0.0.0.0:9001
Available tools: echo, calculator, random

To register with the gateway, run:
curl -X POST http://localhost:8080/agents ...

New connection from ('127.0.0.1', 54321)
← Received: {
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "echo",
    "arguments": {"message": "Hello!"}
  }
}
→ Sending: {
  "jsonrpc": "2.0",
  "id": 1,
  "result": {"echo": "Hello!", "length": 6}
}
```

### Client
```
MCP Gateway Example Client
===========================

Connecting to ws://localhost:8080/mcp...
Connected!

=== Initializing Session ===
→ Sending: {
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  ...
}
← Received: {
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    ...
  }
}

=== Listing Available Tools ===
Found 3 tools:
  - echo: Echo back the input message
  - calculator: Perform basic arithmetic operations
  - random: Generate a random number
```

## Troubleshooting

### "Connection refused" errors
- Make sure the MCP Gateway is running on port 8080
- Check that no firewall is blocking connections

### "No tools available"
- Ensure agents are registered with the gateway
- Verify agents are running and reachable
- Check agent health status: `curl http://localhost:8080/agents`

### Python import errors
- Install websockets: `pip install websockets`
- Make sure you're using Python 3.7+

### "jq: command not found"
- Install jq for the test script
- Ubuntu/Debian: `sudo apt install jq`
- macOS: `brew install jq`
- Or remove `| jq .` from curl commands in test_api.sh

## Next Steps

- Modify `mock_agent.py` to add your own tools
- Use `client.py` as a template for your own clients
- Extend `test_api.sh` with additional test cases
- See [../DEPLOYMENT.md](../DEPLOYMENT.md) for production deployment
