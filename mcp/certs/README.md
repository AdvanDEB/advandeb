# TLS Configuration for MCP Gateway

This directory contains TLS certificate files for secure HTTPS connections.

## Generating Self-Signed Certificates (Development)

For development and testing, you can generate self-signed certificates:

```bash
# Generate a private key
openssl genrsa -out certs/key.pem 2048

# Generate a self-signed certificate (valid for 365 days)
openssl req -new -x509 -key certs/key.pem -out certs/cert.pem -days 365 \
  -subj "/C=US/ST=State/L=City/O=Organization/OU=Unit/CN=localhost"
```

## Using Let's Encrypt (Production)

For production deployments, use Let's Encrypt certificates:

```bash
# Install certbot
sudo apt-get install certbot

# Obtain certificate (replace your.domain.com)
sudo certbot certonly --standalone -d your.domain.com

# Copy certificates to this directory
sudo cp /etc/letsencrypt/live/your.domain.com/fullchain.pem certs/cert.pem
sudo cp /etc/letsencrypt/live/your.domain.com/privkey.pem certs/key.pem
```

## Configuration

Enable TLS in `config/local.toml`:

```toml
[tls]
enabled = true
cert_path = "certs/cert.pem"
key_path = "certs/key.pem"
```

Or via environment variables:

```bash
export ADVANDEB_MCP_TLS_ENABLED=true
export ADVANDEB_MCP_TLS_CERT_PATH=certs/cert.pem
export ADVANDEB_MCP_TLS_KEY_PATH=certs/key.pem
```

## Security Notes

- **Never commit certificate files to version control**
- Keep private keys secure with proper file permissions: `chmod 600 certs/key.pem`
- Use strong, production-grade certificates for production deployments
- Regularly rotate certificates before expiration
- Consider using automated certificate management tools like cert-manager in Kubernetes

## Testing TLS Connection

Once TLS is enabled:

```bash
# Test health endpoint
curl -k https://localhost:8080/health

# For production with valid cert
curl https://your.domain.com:8080/health
```

## WebSocket with TLS

When connecting to the MCP WebSocket endpoint with TLS enabled, use `wss://` instead of `ws://`:

```javascript
const ws = new WebSocket('wss://localhost:8080/mcp');
```
