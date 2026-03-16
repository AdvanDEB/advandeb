# MCP Gateway Deployment Guide

This guide covers deploying the AdvanDEB MCP Gateway to production environments.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Development](#local-development)
3. [Configuration](#configuration)
4. [Monitoring](#monitoring)
5. [High Availability](#high-availability)
6. [Security](#security)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements

- **Operating System**: Linux (Ubuntu 22.04+ recommended), macOS, or Windows with WSL2
- **CPU**: 2+ cores recommended
- **Memory**: 2GB+ RAM minimum, 4GB+ recommended
- **Disk**: 1GB for binaries and logs
- **Network**: Ports 8080 (HTTP) or 8443 (HTTPS) accessible

### Software Requirements

- **Rust**: 1.75 or later (for building from source)
- **TLS Certificates**: Required for HTTPS deployment

---

## Local Development

### Building from Source

```bash
# Clone the repository
git clone https://github.com/your-org/advandeb.git
cd advandeb/mcp

# Build in release mode
cargo build --release

# Binary will be at: target/release/advandeb-mcp
```

### Running Locally

```bash
# With default configuration
cargo run --release

# With custom configuration
export ADVANDEB_MCP_BIND=0.0.0.0:8080
export ADVANDEB_MCP_OLLAMA_HOST=http://localhost:11434
cargo run --release

# With config file
cp config/local.toml.example config/local.toml
# Edit config/local.toml with your settings
cargo run --release
```

### Testing

```bash
# Run all tests
cargo test

# Run specific test suite
cargo test --test integration

# Run with logging
RUST_LOG=debug cargo test

# Health check
curl http://localhost:8080/health
```

---

## Configuration

See [CONFIGURATION.md](CONFIGURATION.md) for detailed configuration options.

### Essential Production Settings

```toml
# config/production.toml
bind = "0.0.0.0:8080"

[tls]
enabled = true
cert_path = "/etc/ssl/certs/mcp-gateway.pem"
key_path = "/etc/ssl/private/mcp-gateway.key"

[agents]
health_check_interval_seconds = 15

[pool]
max_idle_per_agent = 10
connection_timeout_seconds = 10

[circuit_breaker]
failure_threshold = 3
timeout_seconds = 30
half_open_max_requests = 5
```

---

## Monitoring

### Prometheus Metrics

The gateway exposes Prometheus metrics at `/metrics`:

```bash
curl http://localhost:8080/metrics
```

**Key Metrics**:
- `mcp_tool_calls_total` - Total tool calls by agent, tool, and status
- `mcp_tool_latency_seconds` - Tool call latency histogram
- `mcp_workflow_runs_total` - Workflow execution counts
- `mcp_websocket_connections` - Active WebSocket connections
- `mcp_pool_idle_connections` - Idle connection pool size

### Grafana Dashboard

Import the provided Grafana dashboard (`grafana/mcp-gateway-dashboard.json`) for visualization.

### Health Checks

```bash
# Basic health check
curl http://localhost:8080/health

# Agent status
curl http://localhost:8080/agents

# Tool listing
curl http://localhost:8080/tools

# Connection pool stats
curl http://localhost:8080/pool/stats
```

---

## High Availability

### Horizontal Scaling

The gateway is stateless and can be horizontally scaled. Run multiple instances on different ports and load-balance with nginx:

```bash
# Instance 1
ADVANDEB_MCP_BIND=0.0.0.0:8080 cargo run --release

# Instance 2
ADVANDEB_MCP_BIND=0.0.0.0:8081 cargo run --release
```

### Load Balancing

Use a load balancer (nginx, HAProxy, Kubernetes Ingress) in front of gateway instances:

**Nginx example**:

```nginx
upstream mcp_gateway {
    least_conn;
    server gateway1:8080;
    server gateway2:8080;
    server gateway3:8080;
}

server {
    listen 443 ssl http2;
    server_name mcp.example.com;
    
    ssl_certificate /etc/ssl/certs/cert.pem;
    ssl_certificate_key /etc/ssl/private/key.pem;
    
    location / {
        proxy_pass http://mcp_gateway;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

### Resilience Features

The gateway includes built-in resilience:
- **Connection Pooling**: Reuses connections to agents
- **Circuit Breakers**: Prevents cascading failures
- **Retries**: Automatic retry with exponential backoff
- **Health Monitoring**: Automatic agent health checks

---

## Security

### TLS/HTTPS

Always use TLS in production:

```toml
[tls]
enabled = true
cert_path = "/etc/ssl/certs/mcp-gateway.pem"
key_path = "/etc/ssl/private/mcp-gateway.key"
```

### Certificate Management

Use cert-manager in Kubernetes for automatic certificate renewal:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: mcp-gateway-cert
  namespace: advandeb
spec:
  secretName: mcp-gateway-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - mcp.advandeb.example.com
```

### Network Security

- **Firewall**: Only expose port 8080/8443
- **VPC/Network Policies**: Restrict access to gateway
- **Agent Authentication**: Configure mutual TLS between gateway and agents

### Best Practices

- Run as non-root user
- Use read-only file systems where possible
- Rotate certificates regularly (90 days for Let's Encrypt)
- Keep dependencies updated
- Use secret management systems (Vault, AWS Secrets Manager)
- Enable audit logging

---

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for detailed troubleshooting guide.

### Quick Checks

```bash
# Check if service is running
curl http://localhost:8080/health

# Check metrics
curl http://localhost:8080/metrics | grep mcp_

# Test agent connectivity
curl http://localhost:8080/agents
```

### Common Issues

1. **Gateway won't start**: Check configuration and port availability
2. **Agents not connecting**: Verify WebSocket URLs and network connectivity
3. **High latency**: Check connection pool settings and circuit breaker status
4. **Certificate errors**: Verify certificate validity and paths

---

## Performance Tuning

### Recommended Settings

**For high throughput** (1000+ req/s):
```toml
[pool]
max_idle_per_agent = 20

[circuit_breaker]
failure_threshold = 10
timeout_seconds = 10
```

**For low latency** (<50ms):
```toml
[pool]
connection_timeout_seconds = 5

[agents]
health_check_interval_seconds = 10
```

### Benchmarking

```bash
# Install wrk
sudo apt-get install wrk

# Benchmark health endpoint
wrk -t4 -c100 -d30s http://localhost:8080/health

# Benchmark with agent calls (requires registered agents)
wrk -t4 -c100 -d30s -s benchmark.lua http://localhost:8080/mcp
```

---

## Support

For issues and questions:
- GitHub Issues: https://github.com/your-org/advandeb/issues
- Documentation: https://docs.advandeb.example.com
- Email: support@advandeb.example.com

---

**Version**: 1.0.0  
**Last Updated**: 2026-03-13
