# Deployment Guide

## Quick Start

### Development Mode

```bash
# Start all services with hot-reload
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Or without docker-compose:
# Terminal 1: Start MongoDB
docker run -d -p 27017:27017 --name advandeb-mongo mongo:7

# Terminal 2: Start backend
cd backend
cp .env.example .env  # Configure environment variables
pip install -r requirements.txt
pip install -e ../../knowledge-builder
uvicorn app.main:app --reload

# Terminal 3: Start frontend
cd frontend
npm install
npm run dev
```

Visit: http://localhost:5173

### Production Mode

```bash
# Build and start services
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

Visit: http://localhost:3000

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

For production deployment, create a `.env.prod` file:

```env
# MongoDB with authentication
MONGO_ROOT_USERNAME=admin
MONGO_ROOT_PASSWORD=secure-password-here

# JWT (use strong random key)
JWT_SECRET_KEY=production-secret-key-64-chars-minimum

# Google OAuth (production credentials)
GOOGLE_CLIENT_ID=production-client-id
GOOGLE_CLIENT_SECRET=production-client-secret
GOOGLE_REDIRECT_URI=https://yourdomain.com/api/auth/callback

# Database
MONGODB_URI=mongodb://admin:secure-password-here@mongodb:27017
MONGODB_DB_NAME=advandeb

# MCP Integration
MCP_SERVER_URL=http://mcp:8080

# Logging
LOG_LEVEL=WARNING
```

---

## Docker Build Optimization

### Frontend Build

The frontend uses a multi-stage build:
1. **Build stage**: Compiles Vue app with Vite optimizations
   - Code splitting (vue-vendor, graph-vendor, ui-vendor, markdown-vendor)
   - Terser minification with console.log removal
   - No source maps in production
2. **Serve stage**: nginx with gzip compression and caching

```bash
# Build frontend manually
cd frontend
docker build -t advandeb-frontend:latest .

# Check build size
docker images advandeb-frontend
```

### Backend Build

The backend uses Python 3.11 slim:
1. Installs dependencies with pip cache disabled
2. Installs knowledge-builder as editable package
3. Runs as non-root user (appuser)
4. Uses 4 uvicorn workers for production

```bash
# Build backend manually (from app/ directory)
docker build -f backend/Dockerfile -t advandeb-backend:latest .

# Check build size
docker images advandeb-backend
```

---

## Health Checks

All services include health checks:

- **Frontend**: `GET /health` (nginx)
- **Backend**: `GET /health` (FastAPI with DB connectivity check)
- **MongoDB**: `mongosh --eval "db.adminCommand('ping')"`

Check service health:
```bash
# All services
docker-compose ps

# Individual health check
curl http://localhost:3000/health  # Frontend
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

- [ ] Build images: `docker-compose build`
- [ ] Start services: `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
- [ ] Verify health: `docker-compose ps`
- [ ] Check logs: `docker-compose logs -f`
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
# Check frontend logs
docker-compose logs frontend

# Rebuild without cache
docker-compose build --no-cache frontend
```

### Backend connection errors

```bash
# Check backend logs
docker-compose logs backend

# Verify MongoDB connection
docker-compose exec mongodb mongosh --eval "db.adminCommand('ping')"

# Check environment variables
docker-compose exec backend env | grep MONGODB
```

### WebSocket connection failures

- Ensure nginx is properly proxying `/ws/*` requests
- Check `proxy_read_timeout` in nginx.conf
- Verify backend WebSocket handler is registered

---

## Scaling

### Horizontal Scaling

The production compose file uses `deploy.replicas` for scaling:

```bash
# Scale backend to 4 instances
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale backend=4

# Scale frontend to 3 instances
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale frontend=3
```

### Load Balancing

For production deployments, use a reverse proxy (nginx/Traefik) in front of the compose stack:

```nginx
upstream advandeb_frontend {
    server frontend1:80;
    server frontend2:80;
    server frontend3:80;
}

server {
    listen 80;
    server_name yourdomain.com;
    
    location / {
        proxy_pass http://advandeb_frontend;
    }
}
```

---

## Backup & Restore

### MongoDB Backup

```bash
# Backup
docker-compose exec mongodb mongodump --out /data/backup

# Restore
docker-compose exec mongodb mongorestore /data/backup
```

### Volume Backup

```bash
# Backup volume
docker run --rm -v advandeb_mongo_data:/data -v $(pwd):/backup alpine tar czf /backup/mongo_data_backup.tar.gz /data

# Restore volume
docker run --rm -v advandeb_mongo_data:/data -v $(pwd):/backup alpine tar xzf /backup/mongo_data_backup.tar.gz -C /
```

---

## References

- [DEV3 Plan](../docs/DEV3-APP-PLAN.md)
- [App Architecture](../docs/MODELING-ASSISTANT-PLAN.md)
- [Docker Compose Docs](https://docs.docker.com/compose/)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [Vite Build Guide](https://vitejs.dev/guide/build.html)
