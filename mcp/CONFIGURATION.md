# Configuration Guide

## Overview

The MCP Gateway supports multiple configuration sources with the following priority (highest to lowest):

1. **Environment variables** (prefix: `ADVANDEB_MCP_`)
2. **Local config file** (`config/local.toml`)
3. **Default config file** (`config/default.toml`)
4. **Built-in defaults**

## Configuration Files

### Location

Configuration files should be placed in the `config/` directory:
- `config/default.toml` - Default configuration (committed to git)
- `config/local.toml` - Local overrides (gitignored, not committed)

### Format

Configuration files use TOML format. Example:

```toml
# Server configuration
bind = "0.0.0.0:8080"

# Ollama configuration
ollama_host = "http://localhost:11434"
ollama_model = "llama2"

# API endpoints
kb_api_base = "http://localhost:8000"
ma_api_base = "http://localhost:9000"

# HTTP client configuration
request_timeout_seconds = 30

[agents]
health_check_interval_seconds = 30
max_agents_per_tool = 10

[pool]
max_idle_per_agent = 5
connection_timeout_seconds = 10

[circuit_breaker]
failure_threshold = 5
timeout_seconds = 30
half_open_max_requests = 3

[tls]
enabled = true
cert_path = "certs/cert.pem"
key_path = "certs/key.pem"
```

## Configuration Options

### Server Settings

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `bind` | `ADVANDEB_MCP_BIND` | `0.0.0.0:8080` | Server listen address and port |

### Ollama Settings

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `ollama_host` | `ADVANDEB_MCP_OLLAMA_HOST` | `http://localhost:11434` | Ollama API base URL |
| `ollama_model` | `ADVANDEB_MCP_OLLAMA_MODEL` | `llama2` | Default model for chat |

### API Endpoints

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `kb_api_base` | `ADVANDEB_MCP_KB_API_BASE` | `http://localhost:8000` | Knowledge Builder API base URL |
| `ma_api_base` | `ADVANDEB_MCP_MA_API_BASE` | `http://localhost:9000` | Modeling Assistant API base URL |

### HTTP Client Settings

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `request_timeout_seconds` | `ADVANDEB_MCP_REQUEST_TIMEOUT_SECONDS` | `30` | HTTP request timeout in seconds |

### Agent Configuration (`[agents]`)

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `health_check_interval_seconds` | `ADVANDEB_MCP_AGENTS_HEALTH_CHECK_INTERVAL_SECONDS` | `30` | Interval between agent health checks |
| `max_agents_per_tool` | `ADVANDEB_MCP_AGENTS_MAX_AGENTS_PER_TOOL` | `10` | Maximum number of agent replicas per tool |

### Connection Pool Configuration (`[pool]`)

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `max_idle_per_agent` | `ADVANDEB_MCP_POOL_MAX_IDLE_PER_AGENT` | `5` | Maximum idle WebSocket connections per agent |
| `connection_timeout_seconds` | `ADVANDEB_MCP_POOL_CONNECTION_TIMEOUT_SECONDS` | `10` | Connection timeout in seconds |

### Circuit Breaker Configuration (`[circuit_breaker]`)

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `failure_threshold` | `ADVANDEB_MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `5` | Number of failures before opening circuit |
| `timeout_seconds` | `ADVANDEB_MCP_CIRCUIT_BREAKER_TIMEOUT_SECONDS` | `30` | Time to wait before trying half-open state |
| `half_open_max_requests` | `ADVANDEB_MCP_CIRCUIT_BREAKER_HALF_OPEN_MAX_REQUESTS` | `3` | Max probe requests in half-open state |

### TLS Configuration (`[tls]`)

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `enabled` | `ADVANDEB_MCP_TLS_ENABLED` | `false` | Enable TLS/HTTPS |
| `cert_path` | `ADVANDEB_MCP_TLS_CERT_PATH` | - | Path to TLS certificate file |
| `key_path` | `ADVANDEB_MCP_TLS_KEY_PATH` | - | Path to TLS private key file |

## Environment Variables

All configuration options can be overridden using environment variables with the `ADVANDEB_MCP_` prefix.

### Naming Convention

- Use uppercase for environment variables
- Nested sections use double underscores: `ADVANDEB_MCP_AGENTS_HEALTH_CHECK_INTERVAL_SECONDS`
- Boolean values: `true` or `false`
- Numeric values: plain numbers without quotes

### Example

```bash
# Server settings
export ADVANDEB_MCP_BIND="0.0.0.0:8443"

# TLS configuration
export ADVANDEB_MCP_TLS_ENABLED=true
export ADVANDEB_MCP_TLS_CERT_PATH=/etc/ssl/certs/gateway.pem
export ADVANDEB_MCP_TLS_KEY_PATH=/etc/ssl/private/gateway.key

# Agent settings
export ADVANDEB_MCP_AGENTS_HEALTH_CHECK_INTERVAL_SECONDS=15

# Run the gateway
cargo run
```

## Configuration Best Practices

### Development

For local development:
1. Use `config/default.toml` for shared defaults
2. Create `config/local.toml` for your personal overrides
3. Don't commit `config/local.toml` (it's gitignored)

```bash
cp config/local.toml.example config/local.toml
# Edit config/local.toml with your settings
```

### Production

For production deployments:
1. Use environment variables for sensitive values (TLS paths, API keys)
2. Use `config/default.toml` for non-sensitive defaults
3. Consider using secret management systems (Kubernetes Secrets, AWS Secrets Manager, etc.)
4. Never commit sensitive values to version control

## Troubleshooting

### Configuration not loading

1. Check file permissions: `config/*.toml` files must be readable
2. Verify TOML syntax: use a TOML validator
3. Check logs for parsing errors
4. Ensure environment variable names are correct (case-sensitive)

### TLS issues

1. Verify certificate files exist and are readable
2. Check certificate validity: `openssl x509 -in certs/cert.pem -text -noout`
3. Ensure private key matches certificate
4. Check file permissions: `chmod 600 certs/key.pem`

### Environment variables not working

1. Prefix must be exact: `ADVANDEB_MCP_`
2. Use underscores for nested paths
3. Boolean values must be lowercase: `true` or `false`
4. Export variables before running: `export VAR=value`

## Validation

To verify your configuration is loaded correctly:

1. Check startup logs for configuration values
2. Query the health endpoint: `curl http://localhost:8080/health`
3. Enable debug logging: `RUST_LOG=debug cargo run`

## Security Considerations

- **Never commit sensitive values** (TLS keys, passwords) to version control
- **Use environment variables or secret management** for production
- **Restrict file permissions** on certificate files: `chmod 600 certs/*.pem`
- **Rotate certificates regularly** before expiration
- **Use strong TLS configurations** in production
- **Enable TLS for production deployments**
