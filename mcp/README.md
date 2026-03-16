# AdvanDEB MCP Gateway

A high-performance WebSocket gateway for routing Model Context Protocol (MCP) tool calls to multiple agent servers with features like load balancing, circuit breakers, connection pooling, and workflow orchestration.

## Features

- **MCP Protocol Support**: Full JSON-RPC 2.0 implementation of the Model Context Protocol
- **Agent Registry**: Dynamic registration and health monitoring of agent servers
- **Load Balancing**: Round-robin distribution across multiple agent replicas
- **Circuit Breakers**: Automatic failure detection and recovery
- **Connection Pooling**: Efficient WebSocket connection reuse
- **Retry Logic**: Exponential backoff for transient failures
- **Workflow Orchestration**: Multi-step workflows with context resolution
- **Observability**: Prometheus metrics for monitoring and debugging
- **TLS/SSL Support**: Secure WebSocket connections (wss://)
- **Configuration Management**: File-based and environment variable configuration

## Quick Start

### Prerequisites

- Rust 1.70+ (with `rustup`)
- (Optional) Ollama running on `localhost:11434` for LLM support

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/advandeb.git
cd advandeb/mcp

# Build the project
cargo build --release

# Run tests
cargo test
```

### Running the Gateway

```bash
# Run with default configuration (HTTP on port 8080)
cargo run

# Or run the release build
./target/release/advandeb-mcp
```

The gateway will start and listen on `http://0.0.0.0:8080` by default.

### Basic Usage

#### 1. Check Gateway Health

```bash
curl http://localhost:8080/health
```

Response:
```json
{
  "status": "ok",
  "ollama_model": "llama2"
}
```

#### 2. Register an Agent

Agents must register themselves with the gateway before they can receive tool calls.

```bash
curl -X POST http://localhost:8080/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-agent",
    "websocket_url": "ws://localhost:9001",
    "tools": [
      {
        "name": "calculator",
        "description": "Perform mathematical calculations",
        "inputSchema": {
          "type": "object",
          "properties": {
            "expression": {"type": "string"}
          }
        }
      }
    ]
  }'
```

#### 3. Connect via WebSocket

Connect to the MCP WebSocket endpoint at `ws://localhost:8080/mcp`:

```javascript
const ws = new WebSocket('ws://localhost:8080/mcp');

// Initialize the connection
ws.send(JSON.stringify({
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "clientInfo": {"name": "my-client", "version": "1.0.0"}
  }
}));

// List available tools
ws.send(JSON.stringify({
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {}
}));

// Call a tool
ws.send(JSON.stringify({
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "calculator",
    "arguments": {"expression": "2 + 2"}
  }
}));
```

#### 4. Run a Workflow

Execute multi-step workflows with automatic context resolution:

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "workflow/run",
    "params": {
      "steps": [
        {
          "tool": "fetch_data",
          "arguments": {"source": "api"}
        },
        {
          "tool": "process_data",
          "arguments": {"data": "{{step0.result}}"}
        }
      ]
    }
  }'
```

## Configuration

The gateway supports multiple configuration methods with the following precedence:

1. Environment variables (highest priority)
2. `config/local.toml`
3. `config/default.toml`
4. Built-in defaults (lowest priority)

### Configuration File

Create `config/local.toml`:

```toml
# Server configuration
bind = "0.0.0.0:8080"

# TLS configuration (optional)
[tls]
enabled = false
cert_path = "certs/cert.pem"
key_path = "certs/key.pem"

# Agent configuration
[agents]
health_check_interval_seconds = 30

# Connection pool
[pool]
max_idle_per_agent = 5

# Circuit breaker
[circuit_breaker]
failure_threshold = 5
timeout_seconds = 60
half_open_max_requests = 3

# Ollama LLM
[ollama]
host = "http://localhost:11434"
model = "llama2"
```

### Environment Variables

All configuration can be overridden with environment variables using the `ADVANDEB_MCP_` prefix:

```bash
export ADVANDEB_MCP_BIND="0.0.0.0:9000"
export ADVANDEB_MCP_TLS_ENABLED="true"
export ADVANDEB_MCP_OLLAMA_MODEL="mistral"
```

See [CONFIGURATION.md](CONFIGURATION.md) for complete configuration reference.

## REST API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/agents` | POST | Register a new agent |
| `/agents` | GET | List all registered agents |
| `/agents/:name` | DELETE | Deregister an agent |
| `/agents/:name/status` | PUT | Update agent status |
| `/pool/stats` | GET | Connection pool statistics |
| `/metrics` | GET | Prometheus metrics |
| `/mcp` | WebSocket | MCP protocol endpoint |

## MCP Protocol Methods

The WebSocket endpoint supports the following JSON-RPC methods:

- `initialize` - Initialize the MCP session
- `tools/list` - List all available tools from registered agents
- `tools/call` - Execute a tool on an agent
- `workflow/run` - Execute a multi-step workflow

See the [MCP Protocol Specification](https://modelcontextprotocol.io/docs) for details.

## Monitoring

### Prometheus Metrics

The gateway exposes Prometheus metrics at `/metrics`:

```bash
curl http://localhost:8080/metrics
```

Key metrics:
- `mcp_tool_calls_total{tool, agent, status}` - Tool call counter
- `mcp_tool_latency_seconds{tool, agent}` - Tool call latency histogram
- `mcp_websocket_connections` - Active WebSocket connections gauge
- `mcp_workflows_total{status}` - Workflow execution counter

### Health Monitoring

Agents are automatically health-checked every 30 seconds (configurable). Agent status:
- **Healthy** - Agent responding to health checks
- **Degraded** - Agent experiencing issues but still available
- **Unavailable** - Agent not responding

## Development

### Project Structure

```
mcp/
├── src/
│   ├── main.rs              # Entry point
│   ├── lib.rs               # HTTP router and server
│   ├── config.rs            # Configuration management
│   ├── metrics.rs           # Prometheus metrics
│   ├── ollama.rs            # Ollama client
│   ├── mcp/
│   │   ├── protocol.rs      # MCP protocol types
│   │   └── server.rs        # WebSocket handler
│   ├── gateway/
│   │   ├── registry.rs      # Agent registry
│   │   ├── router.rs        # Tool routing
│   │   ├── pool.rs          # Connection pooling
│   │   ├── balancer.rs      # Load balancing
│   │   ├── circuit_breaker.rs  # Circuit breaker
│   │   └── retry.rs         # Retry logic
│   └── workflow/
│       ├── context.rs       # Context resolution
│       └── executor.rs      # Workflow execution
├── tests/                   # Integration tests
├── config/                  # Configuration files
└── certs/                   # TLS certificates
```

### Running Tests

```bash
# Run all tests
cargo test

# Run unit tests only
cargo test --lib

# Run integration tests
cargo test --test '*'

# Run specific test module
cargo test gateway::pool

# Run with output
cargo test -- --nocapture
```

### Building Documentation

```bash
# Generate API documentation
cargo doc --no-deps --open
```

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for comprehensive deployment guides including:
- High availability configurations
- Production best practices
- Security hardening

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for:
- Common issues and solutions
- Diagnostic commands
- Log analysis
- Performance tuning
- Debugging workflows

## Architecture

### Request Flow

```
Client → WebSocket → MCP Gateway → Load Balancer → Agent
                         ↓
                    Registry
                         ↓
                   Circuit Breaker
                         ↓
                 Connection Pool
                         ↓
                   Retry Logic
```

### Key Components

1. **MCP Server** (`mcp/server.rs`): Handles WebSocket connections and MCP protocol messages
2. **Agent Registry** (`gateway/registry.rs`): Tracks registered agents and their tools
3. **Router** (`gateway/router.rs`): Routes tool calls to appropriate agents
4. **Load Balancer** (`gateway/balancer.rs`): Distributes load across agent replicas
5. **Circuit Breaker** (`gateway/circuit_breaker.rs`): Prevents cascading failures
6. **Connection Pool** (`gateway/pool.rs`): Manages WebSocket connections
7. **Workflow Executor** (`workflow/executor.rs`): Executes multi-step workflows

## Performance

- **Tool Call Overhead**: < 50ms (target)
- **Concurrent Connections**: 100+ WebSocket connections
- **Circuit Breaker Recovery**: Automatic with exponential backoff
- **Connection Pooling**: Up to 5 idle connections per agent

## Testing

Current test coverage: **67 tests** (55 unit + 5 config + 1 health + 4 integration + 2 doc tests)

All tests passing ✅

## License

[Your License Here]

## Contributing

[Contribution guidelines]

## Support

For issues and questions:
- GitHub Issues: [your-repo/issues]
- Documentation: [DEPLOYMENT.md](DEPLOYMENT.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- Configuration: [CONFIGURATION.md](CONFIGURATION.md)
