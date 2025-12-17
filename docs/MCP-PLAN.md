# advandeb-MCP Implementation Plan

## Overview

The **advandeb-MCP** component is a high-performance Model Context Protocol (MCP) server written in Rust. It serves as an **internal tool server** for the AdvanDEB platform, exposing both knowledge building and modeling operations as MCP tools for LLM agent workflows.

## Goals

1. **Tool Exposure**: Expose platform operations (knowledge building + modeling) as MCP tools
2. **Performance**: Fast, resource-efficient service for compute-intensive agent operations
3. **Standardization**: Implement MCP specification for LLM agent integration
4. **Unified LLM Gateway**: Single point of integration with Ollama for the platform
5. **No Authentication**: Operates within trusted platform boundary as internal service
6. **Extensibility**: Easy to add new tools as platform capabilities evolve

## Architecture

### Core Components

**HTTP Server (Axum)**:
- Health check endpoint (`/health`)
- Chat endpoint (`/chat`) for basic Ollama interaction
- Future: MCP WebSocket endpoints for real-time agent communication

**Ollama Client**:
- Async HTTP client for Ollama API
- Configurable model selection
- Timeout and error handling
- Supports chat-based interactions with message history

**Configuration System**:
- Environment-based configuration with `ADVANDEB_MCP_` prefix
- Defaults for local development
- Production-ready settings for deployment

**State Management**:
- Shared application state with Axum
- Ollama client pooling
- Future: KB/MA API clients with connection pooling

### Current Implementation

**Technology Stack**:
- **Language**: Rust 2021 edition
- **Web Framework**: Axum 0.7 (async, high-performance HTTP)
- **HTTP Client**: Reqwest 0.12 (with rustls for TLS)
- **Async Runtime**: Tokio 1.37 (multi-threaded)
- **Serialization**: Serde + serde_json
- **Error Handling**: thiserror + anyhow
- **Logging**: tracing + tracing-subscriber
- **Config**: envy (environment variable parsing)

**Endpoints**:
1. `GET /health` - Health check with Ollama model information
2. `POST /chat` - Chat with Ollama models
   - Request: `{ "messages": [...], "model": "optional" }`
   - Response: `{ "reply": "..." }`

**Configuration Variables** (prefix: `ADVANDEB_MCP_`):
- `BIND` - Server bind address (default: `0.0.0.0:8080`)
- `OLLAMA_HOST` - Ollama API URL (default: `http://localhost:11434`)
- `OLLAMA_MODEL` - Default model name (default: `llama2`)
- `KB_API_BASE` - Knowledge Builder API base URL (default: `http://localhost:8000`)
- `MA_API_BASE` - Modeling Assistant API base URL (default: `http://localhost:9000`)
- `REQUEST_TIMEOUT_SECONDS` - HTTP request timeout (default: `30`)

## Integration with AdvanDEB Platform

### Internal Service Architecture

**No Authentication Required**:
- MCP server operates as a trusted internal service within the platform
- Only accessible by Modeling Assistant backend (not exposed externally)
- Deployed within same private network/Kubernetes namespace
- Modeling Assistant handles all user authentication and authorization
- MCP focuses purely on tool execution and LLM operations

**Service Boundaries**:
1. **User Layer**: Users authenticate with Modeling Assistant via Google OAuth (JWT tokens)
2. **Application Layer**: MA validates user permissions and makes internal calls to MCP
3. **MCP Layer**: Executes tools (wrapping KB operations) and LLM inference
4. **Data Layer**: Direct access to MongoDB and Ollama

**Component Relationships**:
- **Modeling Assistant** imports **Knowledge Builder** toolkit as Python package
- **Modeling Assistant** calls **MCP Server** for agent-powered features
- **MCP Server** wraps **Knowledge Builder** operations as MCP tools
- MCP provides LLM inference via Ollama for chat and intelligent features

**Audit Logging**:
- Modeling Assistant logs user actions before calling MCP
- MCP optionally logs internal operations for debugging
- User attribution maintained at MA layer, not MCP layer

### Knowledge Builder Integration

**MCP Tools Wrapping KB Operations**:
- `ingest_document` - Document ingestion pipeline (wraps KB package function)
- `extract_facts` - Extract facts from text using KB agents
- `generate_stylized_facts` - Create stylized facts from fact collections
- `search_facts` - Search biological facts by keywords, entities, or topics
- `get_fact_details` - Retrieve detailed information about a specific fact
- `query_knowledge_graph` - Traverse knowledge graph relationships
- `build_graph_segment` - Generate knowledge graph from facts

**Implementation Approach**:
- MCP calls Knowledge Builder package functions (Python via PyO3 or HTTP bridge)
- Or: MA backend provides HTTP API that MCP calls (simpler integration)
- KB operations wrapped as MCP tools with proper parameter schemas
- MCP handles Ollama integration for LLM-powered KB features
- Direct MongoDB access for fast knowledge queries

### Modeling Assistant Integration

**MCP Tools for MA Features**:
- `chat_with_knowledge` - LLM chat with knowledge base context
- `analyze_scenario` - Analyze modeling scenario assumptions
- `search_scenarios` - Find modeling scenarios by description
- `retrieve_relevant_knowledge` - Get KB data relevant to modeling question
- `explain_model_assumptions` - Reasoning behind model decisions
- `suggest_parameters` - Suggest scenario parameters based on knowledge

**Implementation Approach**:
- MA backend calls MCP for all agent-powered and chat features
- MCP provides the LLM inference layer (via Ollama)
- Tools combine knowledge retrieval (from KB) with LLM reasoning
- Simplified integration: MA → MCP → Ollama + KB queries

## MCP Protocol Implementation

### WebSocket Endpoints (Planned)

**Connection Flow**:
1. KB or MA backend connects to `ws://mcp-service:8080/mcp`
2. No authentication handshake - trusted internal connection
3. Bi-directional message exchange following MCP specification
4. Server maintains session state per connection

**Message Types**:
- `initialize` - Establish session and exchange capabilities
- `tools/list` - Return available tools
- `tools/call` - Execute a specific tool with parameters
- `resources/list` - List accessible knowledge resources
- `resources/read` - Read content of a specific resource
- `prompts/list` - List available prompt templates
- `prompts/get` - Retrieve a prompt template

### Tool Registry

**Dynamic Tool Registration**:
```rust
struct ToolRegistry {
    tools: HashMap<String, Box<dyn Tool>>,
}
```

**Tool Interface**:
```rust
#[async_trait]
trait Tool: Send + Sync {
    fn name(&self) -> &str;
    fn description(&self) -> &str;
    fn parameters(&self) -> serde_json::Value; // JSON Schema
    async fn execute(&self, params: serde_json::Value) -> Result<serde_json::Value>;
}
```

## Development Roadmap

### Phase 1: Foundation (Current - Completed)
- ✅ Rust project setup with Cargo
- ✅ Axum HTTP server with health endpoint
- ✅ Ollama client integration
- ✅ Basic chat endpoint
- ✅ Environment-based configuration
- ✅ Logging infrastructure
- ✅ Basic integration tests

### Phase 2: MCP Protocol (Next - 3-4 weeks)
- Implement WebSocket endpoint for MCP
- Message routing and validation
- Tool registry and dynamic tool loading
- Basic tool implementations (echo, ping)
- MCP client compatibility testing
- Error handling and logging improvements

### Phase 3: Knowledge Builder Tools (4-5 weeks)
- MongoDB client for direct database access (read-only)
- Fact search and retrieval tools
- Document search tools
- Knowledge graph traversal tools
- Stylized fact access tools
- Caching layer for frequent queries

### Phase 4: Modeling Assistant Tools (3-4 weeks)
- Scenario management tools
- Knowledge retrieval for modeling tools
- Model explanation tools
- Integration testing with MA backend

### Phase 5: Production Readiness (3-4 weeks)
- Docker containerization
- Kubernetes deployment manifests (internal service)
- Health checks and readiness probes
- Metrics and monitoring (Prometheus)
- Performance benchmarking
- Load testing and optimization
- Documentation and deployment guides

## Deployment Considerations

### Docker Container

**Dockerfile** (to be created):
```dockerfile
FROM rust:1.75 as builder
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/release/advandeb-mcp /usr/local/bin/
EXPOSE 8080
CMD ["advandeb-mcp"]
```

### Kubernetes Deployment

**Service Configuration**:
- Deployed as internal ClusterIP service (not exposed externally)
- Only accessible within Kubernetes cluster by KB and MA pods
- Service name: `mcp-service` or `advandeb-mcp-service`

**Resource Requirements**:
- CPU: 100m-500m (request-limit)
- Memory: 128Mi-512Mi
- Horizontal scaling based on connection count

**Configuration**:
- ConfigMap for service URLs and settings
- No secrets needed (no authentication)
- Environment variables for MongoDB and Ollama endpoints

### Monitoring

**Metrics to Track**:
- Request count and latency per tool
- Ollama response times
- MongoDB query performance
- Active WebSocket connections
- Memory and CPU usage
- Error rates by type

**Health Checks**:
- Liveness: HTTP `/health` endpoint
- Readiness: Verify Ollama and MongoDB connectivity
- Startup: Allow time for initial connections

## Testing Strategy

### Unit Tests
- Configuration loading and validation
- Ollama client request/response handling
- Tool parameter validation
- MongoDB query operations

### Integration Tests
- End-to-end HTTP request flow
- WebSocket connection lifecycle
- Tool execution with real MongoDB and Ollama
- KB and MA integration scenarios

### Performance Tests
- Concurrent request handling
- WebSocket connection scalability
- Memory usage under load
- Response time distribution

## Security Considerations

1. **Network Isolation**: Deploy as internal service, not exposed to public internet
2. **Input Validation**: Strict validation of all tool parameters
3. **SQL/NoSQL Injection**: Use parameterized queries for database access
4. **Rate Limiting**: Per-connection limits to prevent resource exhaustion
5. **Read-Only Database Access**: MCP should only read from MongoDB, not write
6. **Service Authentication**: Optional mTLS for KB/MA to MCP communication
7. **Audit Trail**: KB and MA log user actions before calling MCP

## Open Questions

1. **MCP Version**: Which version of MCP specification to target?
2. **Tool Versioning**: How to handle tool API changes over time?
3. **Caching Strategy**: Redis vs in-memory caching for tool results?
4. **Database Access**: Read-only MongoDB access or also allow writes for certain tools?
5. **Streaming**: Support for streaming large tool results?
6. **Service Mesh**: Use Istio/Linkerd for mTLS between services?

## References

- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [Axum Documentation](https://docs.rs/axum/)
- [Tokio Async Runtime](https://tokio.rs/)
- Knowledge Builder API (to be documented)
- Modeling Assistant API (to be documented)
