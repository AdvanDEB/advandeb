# AdvanDEB — App

**Status**: Internal beta — under active development (2026-08).
**Version**: 0.1.0

> Note: this component was historically called the "Modeling Assistant." The
> modeling assistant proper is Phase 2 and has not been started; this is the
> AdvanDEB application itself. See `../docs/SYSTEM-OVERVIEW.md`.

---

## Overview

AdvanDEB is a full-stack web application providing an interactive interface to a curated knowledge graph for Dynamic Energy Budget (DEB) biology. It integrates knowledge building, document management, and AI-powered chat assistance through a modern, responsive UI.

### Key Features

**Real-time Chat Interface**
- WebSocket-based streaming chat
- Agent activity visualization
- Markdown rendering with syntax highlighting
- Multi-session management
- Export conversations

**Interactive Knowledge Graph**
- Cosmograph WebGL canvas
- Multiple layouts (Force, Tree, Circle, Rings)
- Node filtering and search
- Graph expansion
- Multiple graph types (Knowledge, Citation, Taxonomy)

**Provenance Tracking**
- Citation trails (Answer → Facts → Chunks → Documents)
- Expandable chunk context
- Source document linking
- Note: trails are **reconstructed on read**, not persisted — a historical
  answer's evidence chain cannot be audited after the fact. See
  `../docs/STORAGE-CONTRACT.md` §5.

**Document Management**
- Drag-and-drop upload
- PDF processing
- Search and filtering
- Embedding status tracking

---

## Architecture

```
app/
├── backend/               # FastAPI backend (serves /api/* and the built SPA)
│   ├── app/
│   │   ├── api/routes/   # API endpoints
│   │   ├── services/     # Business logic
│   │   ├── models/       # Pydantic models
│   │   ├── core/         # Config, auth, database
│   │   └── clients/      # MCP client
│   └── requirements.txt
│
├── frontend/             # Vue 3 frontend (built into backend's static dir)
│   ├── src/
│   │   ├── views/       # Page components
│   │   ├── components/  # Reusable components
│   │   ├── stores/      # Pinia state management
│   │   ├── utils/       # API client, helpers
│   │   └── router/      # Vue Router config
│   └── package.json
│
├── DEPLOYMENT.md              # Deployment guide
├── MONITORING.md              # Monitoring setup
└── README.md                  # This file
```

---

## Quick Start

### Development Mode

```bash
cd advandeb/app

# Terminal 1: Backend (serves /api/* on :8400)
cd backend
cp .env.example .env  # Configure environment
pip install -r requirements.txt
pip install -e ../../knowledge-builder
uvicorn app.main:app --reload --port 8400

# Terminal 2: Frontend dev server (Vite, hot-reload on :5173)
cd frontend
npm install
npm run dev
```

Access the dev UI at: **http://localhost:5173** (proxies `/api/*` to the backend on :8400).

### Production Mode

In production there is no separate web server in front of the app — the FastAPI backend serves both the JSON API at `/api/*` and the built Vue SPA from `frontend/dist/` on port **8400**.

```bash
# Build the frontend (output goes to frontend/dist/)
cd frontend
npm run build

# Run the backend; it will mount and serve dist/
cd ../backend
uvicorn app.main:app --port 8400
```

For canonical ops instructions (systemd unit, service management, environment), see [`RUNNING.md`](../RUNNING.md) at the repo root.

---

## Environment Configuration

### Backend (.env)

**Required:**
```env
JWT_SECRET_KEY=your-secret-key-here
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8400/api/auth/callback
MONGODB_URI=mongodb://localhost:27017
```

**Optional:**
```env
MCP_SERVER_URL=http://localhost:8080
OLLAMA_BASE_URL=http://localhost:11434
CORS_ORIGINS=http://localhost:5173
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
# Output: dist/ (served by the FastAPI backend in production)

# Analyze bundle size
npx vite-bundle-visualizer
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

See [DEPLOYMENT.md](DEPLOYMENT.md) for deployment guide and [`RUNNING.md`](../RUNNING.md) for canonical ops instructions.

---

## Monitoring

See [MONITORING.md](MONITORING.md) for monitoring setup including:
- Sentry error tracking
- Prometheus metrics
- Structured logging
- Alert configuration

---

## API Documentation

When running the backend, interactive API docs are available at:
- **Swagger UI**: http://localhost:8400/docs
- **ReDoc**: http://localhost:8400/redoc

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
- **Graph**: Cosmograph (WebGL)
- **Markdown**: marked + highlight.js
- **Testing**: Vitest

### Backend
- **Framework**: FastAPI
- **Language**: Python 3.11
- **Datastores**: ArangoDB (canonical knowledge), ChromaDB (vectors),
  MongoDB via Motor (application state + materialized graphs).
  See `../docs/STORAGE-CONTRACT.md`.
- **Authentication**: JWT + native password; Google OAuth implemented but
  currently hidden in the UI; GitHub OAuth device flow
- **WebSockets**: FastAPI WebSockets
- **Testing**: pytest + pytest-asyncio

### Infrastructure
- **Web server**: FastAPI (uvicorn) on :8400 — serves API and the built SPA
- **Process management**: systemd — `advandeb.target` pulls in `advandeb.service`
  (backend) and `advandeb-stack.service` (MCP gateway + 6 agents)
- **Monitoring**: Prometheus/Grafana configs under `../monitoring/`; Prometheus
  currently scrapes the MCP gateway (:8080), node exporter, and itself. The
  backend exposes no metrics endpoint yet. Sentry is **not** integrated.

---

## Project Timeline

See [`docs/ROADMAP.md`](../docs/ROADMAP.md) for current phase status and outstanding work.

---

## Integration

### With Knowledge Builder
- Imports `advandeb_kb` package (`pip install -e ../../knowledge-builder`)
- Shares the MongoDB application database (`advandeb`)
- Reads canonical knowledge from ArangoDB (via KB) and renders the
  *materialized* graph from Mongo `graph_nodes` / `graph_edges`
- Note: a second Mongo database, `advandeb_knowledge_builder_kb`, is a
  transitional Mongo→Arango migration remnant. Do not add new writers to it.

### With MCP Gateway
- MCP client for tool calls
- WebSocket streaming for agent updates
- No authentication (internal service)

---

## User Roles

Defined in `backend/app/core/dependencies.py`:

- **Administrator**: Full access
- **Knowledge Curator**: Create/edit knowledge, run agents
- **Knowledge Explorator**: Read-only access; the default role on account creation

Role enforcement via FastAPI dependencies.

**Not implemented:** the `capabilities` field on the user model is initialised
to `[]` and never granted or checked. The capability set described in older
docs (Knowledge Creation, Agent Access, Analytics Access, Reviewer Status) is a
design, not a feature.

**No anonymous access.** Every route requires authentication, including
read-only browsing.

---

## Security

- JWT-based authentication with enforced `type` claims (access vs refresh)
- Refresh-token revocation on logout (`revoked_tokens`, TTL-indexed)
- `slowapi` rate limiting on auth endpoints
- Constant-time login (bcrypt against a dummy hash on user-not-found)
- `JWT_SECRET_KEY` validator rejects unset/short/example secrets outside development
- Google OAuth integration (currently hidden in the UI)
- CORS configuration
- Security headers (X-Frame-Options, X-Content-Type-Options, etc.)
- Environment variable secrets

---

## Troubleshooting

### Frontend not loading
```bash
# In dev: make sure the Vite dev server is running on :5173
cd frontend && npm run dev

# In prod: the FastAPI backend serves frontend/dist/ — make sure you ran
#   npm run build
# and that the backend is up on :8400.
```

### Backend connection errors
```bash
# Check backend logs from uvicorn (or journalctl -u advandeb)
# Verify MongoDB is running:
mongosh --eval "db.adminCommand('ping')"
```

### WebSocket connection failures
- Verify the backend is reachable on :8400
- Check backend WebSocket registration in `main.py`
- In dev, confirm the Vite proxy forwards `/ws/*` to the backend

---

## Resources

- [Roadmap](../docs/ROADMAP.md)
- [System overview](../docs/SYSTEM-OVERVIEW.md)
- [Running the app](../RUNNING.md)
- [Deployment Guide](DEPLOYMENT.md)
- [Monitoring Guide](MONITORING.md)
- [Vue 3 Docs](https://vuejs.org/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)

---

## License

[License information]

---

**Last Updated**: 2026-05-18
