# MCP Gateway Troubleshooting Guide

This guide helps diagnose and resolve common issues with the AdvanDEB MCP Gateway.

## Table of Contents

1. [Quick Diagnostics](#quick-diagnostics)
2. [Startup Issues](#startup-issues)
3. [Connectivity Issues](#connectivity-issues)
4. [Performance Issues](#performance-issues)
5. [Agent Registration Issues](#agent-registration-issues)
6. [TLS/Certificate Issues](#tlscertificate-issues)
7. [Configuration Issues](#configuration-issues)
8. [Logging and Debugging](#logging-and-debugging)

---

## Quick Diagnostics

Run these commands to quickly assess the gateway status:

```bash
# 1. Check if the service is running
curl http://localhost:8080/health
# Expected: {"status":"ok","ollama_model":"..."}

# 2. Check registered agents
curl http://localhost:8080/agents
# Expected: {"agents":[...]}

# 3. Check available tools
curl http://localhost:8080/tools
# Expected: {"tools":[...]}

# 4. Check metrics
curl http://localhost:8080/metrics
# Expected: Prometheus metrics output

# 5. Check connection pool
curl http://localhost:8080/pool/stats
# Expected: {"idle_connections":N}
```

---

## Startup Issues

### Gateway Won't Start

**Symptoms**: Gateway exits immediately or fails to bind to port

**Diagnosis**:
```bash
# Check if port is already in use
netstat -tulpn | grep 8080
# or
lsof -i :8080

# Check configuration
RUST_LOG=debug cargo run
```

**Solutions**:

1. **Port already in use**:
   ```bash
   # Kill existing process
   kill $(lsof -t -i:8080)
   
   # Or change port in configuration
   export ADVANDEB_MCP_BIND=0.0.0.0:8081
   ```

2. **Permission denied** (port < 1024):
   ```bash
   # Use port >= 1024, or run with sudo (not recommended)
   export ADVANDEB_MCP_BIND=0.0.0.0:8080
   ```

3. **Configuration file not found**:
   ```bash
   # Verify config files exist
   ls -la config/
   
   # Use environment variables as fallback
   export ADVANDEB_MCP_BIND=0.0.0.0:8080
   export ADVANDEB_MCP_OLLAMA_HOST=http://localhost:11434
   ```

### Configuration Parse Errors

**Symptoms**: "Failed to parse configuration" error on startup

**Diagnosis**:
```bash
# Validate TOML syntax
cat config/local.toml

# Check for common issues:
# - Missing quotes around strings
# - Unescaped backslashes in paths
# - Invalid section headers
```

**Solutions**:

1. **Fix TOML syntax**:
   ```toml
   # Wrong
   bind = 0.0.0.0:8080
   
   # Correct
   bind = "0.0.0.0:8080"
   ```

2. **Remove invalid sections**:
   ```toml
   # Wrong
   [unknown_section]
   
   # Valid sections: [tls], [agents], [pool], [circuit_breaker]
   ```

3. **Use config file validator**:
   ```bash
   # Online TOML validator: https://www.toml-lint.com/
   ```

---

## Connectivity Issues

### Cannot Connect to Gateway

**Symptoms**: Connection refused, timeout, or network unreachable

**Diagnosis**:
```bash
# 1. Check if gateway is listening
netstat -tulpn | grep 8080

# 2. Check firewall rules
sudo iptables -L -n | grep 8080

# 3. Test from different locations
curl http://localhost:8080/health        # Local
curl http://192.168.1.10:8080/health    # Network
curl http://public-ip:8080/health       # Internet
```

**Solutions**:

1. **Bind to all interfaces**:
   ```toml
   # config/local.toml
   bind = "0.0.0.0:8080"  # Not "127.0.0.1:8080"
   ```

2. **Open firewall port**:
   ```bash
   # UFW
   sudo ufw allow 8080/tcp
   
   # iptables
   sudo iptables -A INPUT -p tcp --dport 8080 -j ACCEPT
   ```

3. **Verify the process is listening**:
   ```bash
   ss -tlnp | grep 8080
   ```

### WebSocket Connection Drops

**Symptoms**: WebSocket connections closing unexpectedly

**Diagnosis**:
```bash
# Check connection timeout settings
curl http://localhost:8080/pool/stats

# Monitor WebSocket gauge
curl http://localhost:8080/metrics | grep mcp_websocket_connections
```

**Solutions**:

1. **Increase connection timeout**:
   ```toml
   [pool]
   connection_timeout_seconds = 30  # Default: 10
   ```

2. **Adjust load balancer timeouts** (if using nginx/HAProxy):
   ```nginx
   # nginx
   proxy_read_timeout 300s;
   proxy_send_timeout 300s;
   ```

3. **Check agent health**:
   ```bash
   curl http://localhost:8080/agents
   # Look for "status": "Unavailable"
   ```

---

## Performance Issues

### High Latency

**Symptoms**: Tool calls taking > 100ms

**Diagnosis**:
```bash
# Check metrics
curl http://localhost:8080/metrics | grep mcp_tool_latency

# Check connection pool utilization
curl http://localhost:8080/pool/stats

# Enable debug logging
RUST_LOG=debug cargo run
```

**Solutions**:

1. **Increase connection pool size**:
   ```toml
   [pool]
   max_idle_per_agent = 20  # Default: 5
   ```

2. **Reduce health check frequency**:
   ```toml
   [agents]
   health_check_interval_seconds = 60  # Default: 30
   ```

3. **Check circuit breaker status**:
   ```bash
   # Circuit breakers may be tripping
   curl http://localhost:8080/metrics | grep circuit_breaker
   ```

4. **Scale horizontally**:
   ```bash
   # Kubernetes
   kubectl scale deployment mcp-gateway --replicas=5
   ```

### High Memory Usage

**Symptoms**: Gateway using excessive memory (> 1GB)

**Diagnosis**:
```bash
# Check memory usage
ps aux | grep mcp-gateway
```

**Solutions**:

1. **Reduce pool size**:
   ```toml
   [pool]
   max_idle_per_agent = 3  # Default: 5
   ```

2. **Limit agent count**:
   ```toml
   [agents]
   max_agents_per_tool = 5  # Default: 10
   ```

3. **Set resource limits** (Kubernetes):
   ```yaml
   resources:
     limits:
       memory: "512Mi"
   ```

### Connection Pool Exhaustion

**Symptoms**: "No available connections" errors

**Diagnosis**:
```bash
curl http://localhost:8080/pool/stats
# Check if idle_connections is always 0
```

**Solutions**:

1. **Increase max idle connections**:
   ```toml
   [pool]
   max_idle_per_agent = 10
   ```

2. **Check for connection leaks**:
   ```bash
   # Monitor over time
   watch -n 1 'curl -s http://localhost:8080/pool/stats'
   ```

---

## Agent Registration Issues

### Agent Won't Register

**Symptoms**: `POST /agents` returns error or agent not listed

**Diagnosis**:
```bash
# Attempt registration
curl -X POST http://localhost:8080/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test_agent",
    "websocket_url": "ws://localhost:8081",
    "tools": []
  }'

# Check logs for errors
RUST_LOG=debug cargo run
```

**Solutions**:

1. **Verify JSON format**:
   ```bash
   # Correct format
   {
     "name": "agent_name",
     "websocket_url": "ws://host:port",
     "tools": [
       {
         "name": "tool_name",
         "description": "Tool description",
         "inputSchema": {}
       }
     ]
   }
   ```

2. **Check WebSocket URL**:
   ```bash
   # Test agent connectivity
   wscat -c ws://localhost:8081
   ```

3. **Verify tools array**:
   ```bash
   # Empty array is valid, but must be present
   "tools": []
   ```

### Agent Marked as Unavailable

**Symptoms**: Agent shows `"status": "Unavailable"` in listing

**Diagnosis**:
```bash
# Check agent list
curl http://localhost:8080/agents

# Check agent health endpoint
curl http://localhost:8081/health  # Replace with agent's HTTP port
```

**Solutions**:

1. **Ensure agent has health endpoint**:
   ```bash
   # Agent must expose HTTP /health endpoint
   # Convert ws://localhost:8081 -> http://localhost:8081/health
   ```

2. **Check network connectivity**:
   ```bash
   # From gateway server
   curl http://agent-host:8081/health
   ```

3. **Verify agent is running**:
   ```bash
   # Check agent process
   ps aux | grep agent
   
   # Check agent logs
   tail -f logs/agents/retrieval_agent.log
   ```

---

## TLS/Certificate Issues

### Certificate Not Found

**Symptoms**: "Failed to load certificate" error on startup

**Diagnosis**:
```bash
# Check if certificate files exist
ls -la certs/

# Verify paths in configuration
cat config/local.toml | grep cert_path
```

**Solutions**:

1. **Generate self-signed certificates** (development):
   ```bash
   cd certs
   openssl genrsa -out key.pem 2048
   openssl req -new -x509 -key key.pem -out cert.pem -days 365 \
     -subj "/C=US/ST=State/L=City/O=Org/CN=localhost"
   ```

2. **Fix file paths**:
   ```toml
   [tls]
   enabled = true
   cert_path = "certs/cert.pem"  # Relative to working directory
   key_path = "certs/key.pem"
   ```

3. **Check file permissions**:
   ```bash
   chmod 600 certs/key.pem
   chmod 644 certs/cert.pem
   ```

### Certificate Validation Errors

**Symptoms**: "Invalid certificate" or "Certificate expired"

**Diagnosis**:
```bash
# Check certificate validity
openssl x509 -in certs/cert.pem -text -noout

# Check expiration
openssl x509 -in certs/cert.pem -noout -dates

# Verify certificate chain
openssl verify certs/cert.pem
```

**Solutions**:

1. **Renew expired certificate**:
   ```bash
   # Let's Encrypt
   sudo certbot renew
   
   # Copy new certificates
   sudo cp /etc/letsencrypt/live/domain/fullchain.pem certs/cert.pem
   sudo cp /etc/letsencrypt/live/domain/privkey.pem certs/key.pem
   ```

2. **Use self-signed cert for development**:
   ```bash
   # Client: skip verification (development only!)
   curl -k https://localhost:8443/health
   ```

### TLS Handshake Failures

**Symptoms**: "TLS handshake failed" errors in logs

**Diagnosis**:
```bash
# Test TLS connection
openssl s_client -connect localhost:8443 -showcerts

# Check supported ciphers
openssl s_client -connect localhost:8443 -cipher 'ALL'
```

**Solutions**:

1. **Update TLS library**:
   ```bash
   cargo update
   ```

2. **Disable TLS for troubleshooting**:
   ```toml
   [tls]
   enabled = false
   ```

---

## Configuration Issues

### Environment Variables Not Working

**Symptoms**: Settings not applied despite setting env vars

**Diagnosis**:
```bash
# Verify environment variables are set
env | grep ADVANDEB_MCP

# Check if config file is overriding
cat config/local.toml
```

**Solutions**:

1. **Correct variable naming**:
   ```bash
   # Wrong
   export MCP_BIND=0.0.0.0:8080
   
   # Correct
   export ADVANDEB_MCP_BIND=0.0.0.0:8080
   ```

2. **Nested configuration**:
   ```bash
   # Use double underscores for nested sections
   export ADVANDEB_MCP_TLS_ENABLED=true
   export ADVANDEB_MCP_TLS_CERT_PATH=/certs/cert.pem
   ```

3. **Export before running**:
   ```bash
   export ADVANDEB_MCP_BIND=0.0.0.0:8080
   cargo run  # Must be in same shell session
   ```

### Config File Priority Issues

**Symptoms**: Wrong configuration values being used

**Diagnosis**:
```bash
# Configuration priority (highest to lowest):
# 1. Environment variables
# 2. config/local.toml
# 3. config/default.toml
# 4. Built-in defaults

# Check which files exist
ls -la config/
```

**Solutions**:

1. **Remove conflicting config**:
   ```bash
   # Remove local.toml if you want to use env vars only
   rm config/local.toml
   ```

2. **Debug configuration loading**:
   ```bash
   RUST_LOG=debug cargo run 2>&1 | grep -i config
   ```

---

## Logging and Debugging

### Enable Debug Logging

```bash
# All modules
RUST_LOG=debug cargo run

# Specific modules
RUST_LOG=advandeb_mcp::gateway=debug cargo run

# Multiple modules
RUST_LOG=advandeb_mcp::gateway=debug,advandeb_mcp::mcp=trace cargo run
```

### Log to File

```bash
# Redirect stdout/stderr
cargo run > logs/gateway.log 2>&1
```

### Useful Log Filters

```bash
# Tool call latency
grep "elapsed_ms" logs/gateway.log

# Errors only
grep -i error logs/gateway.log

# Agent health changes
grep -i "health" logs/gateway.log

# Circuit breaker events
grep -i "circuit" logs/gateway.log
```

### Debugging with GDB (if crashes)

```bash
# Build with debug symbols
cargo build

# Run with GDB
rust-gdb target/debug/advandeb-mcp

# Analyze core dump
gdb target/debug/advandeb-mcp core
```

---

## Getting Help

If issues persist after trying these solutions:

1. **Check GitHub Issues**: https://github.com/your-org/advandeb/issues
2. **Enable debug logging** and include logs in issue report
3. **Provide configuration** (sanitize sensitive data)
4. **Include version info**:
   ```bash
   cargo version
   rustc --version
   ./target/release/advandeb-mcp --version
   ```

---

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| "Address already in use" | Port 8080 in use | Change port or kill existing process |
| "Connection refused" | Service not running | Start gateway, check firewall |
| "No agent found for tool" | Agent not registered | Register agent via POST /agents |
| "Failed to load certificate" | Missing cert files | Generate or copy certificates |
| "Parse error" | Invalid JSON/TOML | Validate configuration syntax |
| "Tool call failed" | Agent unreachable | Check agent health and connectivity |
| "Circuit breaker open" | Too many failures | Wait for timeout or restart agents |

---

**Last Updated**: 2026-03-13  
**Version**: 1.0.0
