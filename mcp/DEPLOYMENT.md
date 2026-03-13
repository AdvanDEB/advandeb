# MCP Gateway Deployment Guide

This guide covers deploying the AdvanDEB MCP Gateway to production environments.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Development](#local-development)
3. [Docker Deployment](#docker-deployment)
4. [Kubernetes Deployment](#kubernetes-deployment)
5. [Configuration](#configuration)
6. [Monitoring](#monitoring)
7. [High Availability](#high-availability)
8. [Security](#security)
9. [Troubleshooting](#troubleshooting)

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
- **Docker**: 20.10+ (for containerized deployment)
- **Kubernetes**: 1.25+ (for k8s deployment)
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

## Docker Deployment

### Building Docker Image

Create a `Dockerfile`:

```dockerfile
# Multi-stage build for minimal image size
FROM rust:1.75-bookworm as builder

WORKDIR /app
COPY . .

# Build release binary
RUN cargo build --release

# Runtime image
FROM debian:bookworm-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy binary from builder
COPY --from=builder /app/target/release/advandeb-mcp /usr/local/bin/mcp-gateway

# Copy configuration files
COPY --from=builder /app/config /app/config

# Create non-root user
RUN useradd -m -u 1000 mcp && \
    mkdir -p /app/logs && \
    chown -R mcp:mcp /app

USER mcp
WORKDIR /app

EXPOSE 8080

CMD ["mcp-gateway"]
```

Build the image:

```bash
docker build -t advandeb-mcp:latest .
```

### Running with Docker

```bash
# Basic run
docker run -d \
  --name mcp-gateway \
  -p 8080:8080 \
  advandeb-mcp:latest

# With environment variables
docker run -d \
  --name mcp-gateway \
  -p 8080:8080 \
  -e ADVANDEB_MCP_BIND=0.0.0.0:8080 \
  -e ADVANDEB_MCP_OLLAMA_HOST=http://ollama:11434 \
  advandeb-mcp:latest

# With TLS
docker run -d \
  --name mcp-gateway \
  -p 8443:8443 \
  -e ADVANDEB_MCP_TLS_ENABLED=true \
  -e ADVANDEB_MCP_TLS_CERT_PATH=/certs/cert.pem \
  -e ADVANDEB_MCP_TLS_KEY_PATH=/certs/key.pem \
  -v /path/to/certs:/certs:ro \
  advandeb-mcp:latest

# With custom config
docker run -d \
  --name mcp-gateway \
  -p 8080:8080 \
  -v $(pwd)/config:/app/config:ro \
  advandeb-mcp:latest
```

### Docker Compose

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  mcp-gateway:
    image: advandeb-mcp:latest
    build: .
    ports:
      - "8080:8080"
    environment:
      - ADVANDEB_MCP_BIND=0.0.0.0:8080
      - ADVANDEB_MCP_OLLAMA_HOST=http://ollama:11434
      - RUST_LOG=info
    volumes:
      - ./config:/app/config:ro
      - ./logs:/app/logs
    depends_on:
      - ollama
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama-data:/root/.ollama
    restart: unless-stopped

volumes:
  ollama-data:
```

Run with Docker Compose:

```bash
docker-compose up -d
docker-compose logs -f mcp-gateway
docker-compose ps
```

---

## Kubernetes Deployment

### Prerequisites

- Kubernetes cluster (1.25+)
- `kubectl` configured
- Ingress controller (nginx, traefik, etc.)
- TLS certificates (for HTTPS)

### Deployment Manifests

**1. ConfigMap** (`mcp-gateway-config.yaml`):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-gateway-config
  namespace: advandeb
data:
  ADVANDEB_MCP_BIND: "0.0.0.0:8080"
  ADVANDEB_MCP_OLLAMA_HOST: "http://ollama-service:11434"
  ADVANDEB_MCP_AGENTS_HEALTH_CHECK_INTERVAL_SECONDS: "30"
  RUST_LOG: "info"
```

**2. Secret** (for TLS):

```bash
# Create TLS secret from certificate files
kubectl create secret tls mcp-gateway-tls \
  --cert=/path/to/cert.pem \
  --key=/path/to/key.pem \
  --namespace=advandeb
```

**3. Deployment** (`mcp-gateway-deployment.yaml`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-gateway
  namespace: advandeb
  labels:
    app: mcp-gateway
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mcp-gateway
  template:
    metadata:
      labels:
        app: mcp-gateway
    spec:
      containers:
      - name: mcp-gateway
        image: advandeb-mcp:latest
        ports:
        - containerPort: 8080
          name: http
        envFrom:
        - configMapRef:
            name: mcp-gateway-config
        env:
        - name: ADVANDEB_MCP_TLS_ENABLED
          value: "false"  # TLS terminated at ingress
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
        volumeMounts:
        - name: config
          mountPath: /app/config
          readOnly: true
      volumes:
      - name: config
        configMap:
          name: mcp-gateway-config
```

**4. Service** (`mcp-gateway-service.yaml`):

```yaml
apiVersion: v1
kind: Service
metadata:
  name: mcp-gateway-service
  namespace: advandeb
spec:
  selector:
    app: mcp-gateway
  ports:
  - protocol: TCP
    port: 8080
    targetPort: 8080
    name: http
  type: ClusterIP
```

**5. Ingress** (`mcp-gateway-ingress.yaml`):

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mcp-gateway-ingress
  namespace: advandeb
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - mcp.advandeb.example.com
    secretName: mcp-gateway-tls
  rules:
  - host: mcp.advandeb.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: mcp-gateway-service
            port:
              number: 8080
```

### Deploy to Kubernetes

```bash
# Create namespace
kubectl create namespace advandeb

# Apply manifests
kubectl apply -f mcp-gateway-config.yaml
kubectl apply -f mcp-gateway-deployment.yaml
kubectl apply -f mcp-gateway-service.yaml
kubectl apply -f mcp-gateway-ingress.yaml

# Check status
kubectl get pods -n advandeb
kubectl get svc -n advandeb
kubectl get ingress -n advandeb

# View logs
kubectl logs -f deployment/mcp-gateway -n advandeb

# Scale replicas
kubectl scale deployment mcp-gateway --replicas=5 -n advandeb
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

The gateway is stateless and can be horizontally scaled:

```bash
# Kubernetes
kubectl scale deployment mcp-gateway --replicas=5 -n advandeb

# Docker Compose (with load balancer)
docker-compose up --scale mcp-gateway=3
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

# View logs
docker logs mcp-gateway
kubectl logs -f deployment/mcp-gateway -n advandeb

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
