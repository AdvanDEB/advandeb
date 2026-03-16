# Deployment Guide

## Quick Start

### Development Mode

```bash
# Terminal 1: Start backend
cd backend
cp .env.example .env  # Configure environment variables
pip install -r requirements.txt
pip install -e ../../knowledge-builder
uvicorn app.main:app --reload

# Terminal 2: Start frontend
cd frontend
npm install
npm run dev
```

Visit: http://localhost:5173

### Production Mode

```bash
# Build frontend
cd frontend
npm run build
# Serve dist/ with nginx (see frontend/nginx.conf)

# Start backend
cd backend
uvicorn app.main:app --workers 4
```

---

## Environment Configuration

### Backend Environment Variables

Create `backend/.env` with the following:

**Required:**
```env
# JWT Authentication
JWT_SECRET_KEY=your-secret-key-here-use-openssl-rand-hex-32

# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/callback

# Database
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=advandeb
```

**Optional (with defaults):**
```env
# Application
APP_NAME=AdvanDEB Modeling Assistant
APP_VERSION=0.1.0

# MCP Integration
MCP_SERVER_URL=http://localhost:8080
MCP_SERVER_ENABLED=true

# Ollama
OLLAMA_BASE_URL=http://localhost:11434

# CORS
CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# Logging
LOG_LEVEL=INFO
```

### Production Environment Variables

For production, set these in `backend/.env`:

```env
# MongoDB with authentication
JWT_SECRET_KEY=production-secret-key-64-chars-minimum

# Google OAuth (production credentials)
GOOGLE_CLIENT_ID=production-client-id
GOOGLE_CLIENT_SECRET=production-client-secret
GOOGLE_REDIRECT_URI=https://yourdomain.com/api/auth/callback

# Database
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=advandeb

# MCP Integration
MCP_SERVER_URL=http://localhost:8080

# Logging
LOG_LEVEL=WARNING
```

---

## Health Checks

All services include health checks:

- **Frontend**: `GET /health` (nginx)
- **Backend**: `GET /health` (FastAPI with DB connectivity check)
- **MongoDB**: `mongosh --eval "db.adminCommand('ping')"`

Check service health:
```bash
curl http://localhost:3000/health  # Frontend (nginx)
curl http://localhost:8000/health  # Backend
```

---

## Performance Targets

### Week 12 Success Metrics

- ✅ **Page Load Time**: <3s initial load
- ✅ **Time to First Byte**: <500ms
- ✅ **Bundle Size**: <1MB (gzipped)
- ✅ **Lighthouse Score**: >90
- ✅ **Graph Rendering**: 60fps interactions

### Testing Performance

```bash
# Frontend build size analysis
cd frontend
npm run build
npx vite-bundle-visualizer

# Backend load testing
pip install locust
locust -f tests/load/locustfile.py --host http://localhost:8000

# Lighthouse CI
npm install -g @lhci/cli
lhci autorun --config lighthouserc.json
```

---

## Monitoring & Error Tracking

### Sentry Integration (Optional)

Add to `backend/.env`:
```env
SENTRY_DSN=your-sentry-dsn-here
```

Add to `frontend/.env`:
```env
VITE_SENTRY_DSN=your-sentry-dsn-here
```

### Prometheus Metrics (Optional)

The backend can expose Prometheus metrics at `/metrics`:

```bash
pip install prometheus-fastapi-instrumentator
```

Add to `backend/app/main.py`:
```python
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)
```

---

## Production Deployment Checklist

### Pre-deployment

- [ ] Update `JWT_SECRET_KEY` with strong random value
- [ ] Configure production Google OAuth credentials
- [ ] Set `MONGO_ROOT_PASSWORD` to secure value
- [ ] Set `LOG_LEVEL=WARNING` or `ERROR`
- [ ] Review CORS origins
- [ ] Test health checks locally
- [ ] Run security audit: `npm audit` and `pip-audit`
- [ ] Run tests: `npm test` and `pytest`

### Deployment

- [ ] Build frontend: `npm run build` (from `frontend/`)
- [ ] Start backend: `uvicorn app.main:app --workers 4`
- [ ] Serve frontend dist/ with nginx
- [ ] Verify health endpoints
- [ ] Run smoke tests

### Post-deployment

- [ ] Verify frontend loads: http://yourdomain.com
- [ ] Test authentication flow
- [ ] Test chat functionality
- [ ] Test graph visualization
- [ ] Monitor error rates (Sentry)
- [ ] Monitor performance metrics

---

## Troubleshooting

### Frontend not loading

```bash
# Check nginx is running and serving dist/
# Ensure npm run build has been run
```

### Backend connection errors

```bash
# Check uvicorn output
# Verify MongoDB is running:
mongosh --eval "db.adminCommand('ping')"
# Check environment variables in backend/.env
```

### WebSocket connection failures

- Ensure nginx is properly proxying `/ws/*` requests
- Check `proxy_read_timeout` in nginx.conf
- Verify backend WebSocket handler is registered

---

## Scaling

### Horizontal Scaling

Scale the backend by running multiple uvicorn workers:

```bash
uvicorn app.main:app --workers 4
```

For multiple processes, use a process manager (systemd, supervisor) and put nginx in front.

### Load Balancing

Use nginx as a reverse proxy in front of multiple backend instances:

```nginx
upstream advandeb_backend {
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
    server 127.0.0.1:8003;
}

server {
    listen 80;
    server_name yourdomain.com;

    location /api/ {
        proxy_pass http://advandeb_backend;
    }
}
```

---

## Backup & Restore

### MongoDB Backup

```bash
# Backup
mongodump --out /path/to/backup

# Restore
mongorestore /path/to/backup
```

---

## References

- [DEV3 Plan](../docs/DEV3-APP-PLAN.md)
- [App Architecture](../docs/MODELING-ASSISTANT-PLAN.md)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [Vite Build Guide](https://vitejs.dev/guide/build.html)
