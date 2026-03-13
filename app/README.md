# AdvanDEB Modeling Assistant - App

**Status**: ✅ Production Ready  
**Version**: 0.1.0  
**Developer**: Dev 3 (Full-stack Vue/FastAPI)  
**Development Timeline**: 12 weeks (100% complete)

---

## Overview

The AdvanDEB Modeling Assistant is a full-stack web application that provides an interactive interface for working with Dynamic Energy Budget (DEB) models. It integrates knowledge building, document management, and AI-powered chat assistance through a modern, responsive UI.

### Key Features

✅ **Real-time Chat Interface**
- WebSocket-based streaming chat
- Agent activity visualization
- Markdown rendering with syntax highlighting
- Multi-session management
- Export conversations

✅ **Interactive Knowledge Graph**
- Cytoscape.js visualization
- Multiple layouts (Force, Tree, Circle, Rings)
- Node filtering and search
- Graph expansion
- 3 graph types: Knowledge, Citation, Taxonomy

✅ **Provenance Tracking**
- Full citation trails (Answer → Facts → Chunks → Documents)
- Expandable chunk context
- Source document linking

✅ **Document Management**
- Drag-and-drop upload
- PDF processing
- Search and filtering
- Embedding status tracking

✅ **Production Ready**
- Docker deployment
- Health checks
- Monitoring setup
- Security headers
- Performance optimized

---

## Architecture

```
app/
├── backend/               # FastAPI backend
│   ├── app/
│   │   ├── api/routes/   # API endpoints
│   │   ├── services/     # Business logic
│   │   ├── models/       # Pydantic models
│   │   ├── core/         # Config, auth, database
│   │   └── clients/      # MCP client
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/             # Vue 3 frontend
│   ├── src/
│   │   ├── views/       # Page components
│   │   ├── components/  # Reusable components
│   │   ├── stores/      # Pinia state management
│   │   ├── utils/       # API client, helpers
│   │   └── router/      # Vue Router config
│   ├── Dockerfile
│   ├── nginx.conf
│   └── package.json
│
├── docker-compose.yml         # Base configuration
├── docker-compose.dev.yml     # Development overrides
├── docker-compose.prod.yml    # Production configuration
├── DEPLOYMENT.md              # Deployment guide
├── MONITORING.md              # Monitoring setup
└── README.md                  # This file
```

---

## Quick Start

### Development Mode

```bash
# Clone repository
cd advandeb/app

# Start all services (MongoDB, backend, frontend)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Or run locally without Docker:

# Terminal 1: MongoDB
docker run -d -p 27017:27017 mongo:7

# Terminal 2: Backend
cd backend
cp .env.example .env  # Configure environment
pip install -r requirements.txt
pip install -e ../../knowledge-builder
uvicorn app.main:app --reload

# Terminal 3: Frontend
cd frontend
npm install
npm run dev
```

Access the app at: **http://localhost:5173**

### Production Mode

```bash
# Build and start
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

Access the app at: **http://localhost:3000**

---

## Environment Configuration

### Backend (.env)

**Required:**
```env
JWT_SECRET_KEY=your-secret-key-here
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/callback
MONGODB_URI=mongodb://localhost:27017
```

**Optional:**
```env
MCP_SERVER_URL=http://localhost:8080
OLLAMA_BASE_URL=http://localhost:11434
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
LOG_LEVEL=INFO
```

See `backend/.env.example` for full configuration.

---

## Development

### Running Tests

**Frontend:**
```bash
cd frontend

# Unit tests (Vitest)
npm test
npm run test:watch

# E2E tests (Playwright)
npm run test:e2e
```

**Backend:**
```bash
cd backend

# All tests
pytest

# With coverage
pytest --cov=app --cov-report=html
```

### Building

**Frontend:**
```bash
cd frontend
npm run build
# Output: dist/

# Analyze bundle size
npx vite-bundle-visualizer
```

**Backend:**
```bash
cd backend
docker build -f Dockerfile -t advandeb-backend:latest ..
```

### Code Quality

```bash
# Frontend
cd frontend
npm run lint
npm run format

# Backend
cd backend
black app/
isort app/
mypy app/
```

---

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for comprehensive deployment guide including:
- Environment configuration
- Docker deployment
- Health checks
- Scaling
- Backup/restore

---

## Monitoring

See [MONITORING.md](MONITORING.md) for monitoring setup including:
- Sentry error tracking
- Prometheus metrics
- Lighthouse CI
- Structured logging
- Alert configuration

---

## API Documentation

When running the backend, interactive API docs are available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Key Endpoints

**Authentication:**
- `GET /api/auth/google` - Google OAuth login
- `POST /api/auth/login` - Native login
- `GET /api/auth/me` - Get current user

**Documents:**
- `GET /api/documents` - List documents
- `POST /api/documents/upload` - Upload document
- `POST /api/documents/{id}/embed` - Trigger embedding

**Chat:**
- `POST /api/chat/message` - Send message (REST)
- `WS /ws/chat/{session_id}` - WebSocket chat stream

**Knowledge Graph:**
- `GET /api/graph/{type}` - Get graph data
- `GET /api/graph/expand` - Expand node neighbors
- `GET /api/graph/provenance/{id}` - Get citation trail

---

## Tech Stack

### Frontend
- **Framework**: Vue 3 (Composition API)
- **Language**: TypeScript
- **Build Tool**: Vite
- **State Management**: Pinia
- **Routing**: Vue Router
- **Styling**: Tailwind CSS
- **Graph**: Cytoscape.js
- **Markdown**: marked + highlight.js
- **Testing**: Vitest + Playwright

### Backend
- **Framework**: FastAPI
- **Language**: Python 3.11
- **Database**: MongoDB (Motor async driver)
- **Authentication**: JWT + Google OAuth
- **WebSockets**: FastAPI WebSockets
- **Testing**: pytest + pytest-asyncio

### Infrastructure
- **Containerization**: Docker + Docker Compose
- **Web Server**: nginx (frontend proxy)
- **Reverse Proxy**: nginx
- **Monitoring**: Sentry, Prometheus (optional)

---

## Performance Metrics

### Achieved Metrics (Week 12)

✅ **Frontend:**
- Initial load: 2.1s (target: <3s)
- Bundle size: 645KB gzipped (target: <1MB)
- Build time: 4.3s
- Lighthouse score: 95/100 (target: >90)

✅ **Backend:**
- Health check: <100ms
- Docker image: 200MB (Python 3.11-slim)

✅ **Infrastructure:**
- All services have health checks
- Security headers configured
- Production-ready with resource limits

---

## Integration

### With Dev 1 (Knowledge Builder)
- Imports `advandeb_kb` package
- Shares MongoDB collections
- Uses provenance data format
- Retrieves graph data from ArangoDB (via KB)

### With Dev 2 (MCP Gateway)
- MCP client for tool calls
- WebSocket streaming for agent updates
- No authentication (internal service)

---

## User Roles

Defined in `backend/app/core/dependencies.py`:

- **Administrator**: Full access
- **Knowledge Curator**: Create/edit knowledge, run agents
- **Knowledge Explorator**: Read-only access

Role enforcement via FastAPI dependencies.

---

## Security

- JWT-based authentication
- Google OAuth integration
- CORS configuration
- Security headers (X-Frame-Options, X-Content-Type-Options, etc.)
- Non-root Docker user (backend)
- Environment variable secrets

---

## Project Timeline

**Week 1-2**: Backend MCP integration + Chat interface  
**Week 3-4**: Agent visualization + Provenance display  
**Week 5-6**: Knowledge graph + Mid-point integration  
**Week 7-8**: Document management + Graph enhancements  
**Week 9-10**: Advanced chat features + UI polish  
**Week 11**: Testing (unit + E2E + backend)  
**Week 12**: Production deployment ✅

See [DEV3-LOG.md](../DEV3-LOG.md) for detailed progress log.

---

## Troubleshooting

### Frontend not loading
```bash
docker-compose logs frontend
docker-compose build --no-cache frontend
```

### Backend connection errors
```bash
docker-compose logs backend
docker-compose exec mongodb mongosh --eval "db.adminCommand('ping')"
```

### WebSocket connection failures
- Check nginx is proxying `/ws/*`
- Verify `proxy_read_timeout` in nginx.conf
- Check backend WebSocket registration in `main.py`

---

## Resources

- [Development Plan](../docs/DEV3-APP-PLAN.md)
- [Development Log](../DEV3-LOG.md)
- [Deployment Guide](DEPLOYMENT.md)
- [Monitoring Guide](MONITORING.md)
- [Vue 3 Docs](https://vuejs.org/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Cytoscape.js Docs](https://js.cytoscape.org/)

---

## License

[License information]

---

## Contributors

- **Dev 3**: Full-stack development (Vue 3 + FastAPI)
- **Dev 1**: Knowledge Builder integration
- **Dev 2**: MCP Gateway integration

---

**Status**: ✅ Production Ready  
**Last Updated**: 2026-03-13  
**Next Steps**: Coordinate with Dev 1 & Dev 2 for full system deployment
