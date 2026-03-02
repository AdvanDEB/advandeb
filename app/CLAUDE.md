# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in `app/`.

## Role in the Platform

`app/` is the **single user-facing application** for the entire AdvanDEB platform. All authentication, role-based access control, and user interaction happen here. It integrates the other components:
- Imports `advandeb_kb` as a local editable package (`pip install -e ../../knowledge-builder`)
- Calls `mcp/` (internal HTTP, no auth) for LLM agent features
- Shares MongoDB with the other services

## Current State

**Scaffolded** — the project structure and models are in place but most features are not yet implemented. Active development is ongoing following the 6-phase plan in `docs/MODELING-ASSISTANT-PLAN.md`.

## Running the App

**Backend:**
```bash
cd app/backend
pip install -r requirements.txt
pip install -e ../../knowledge-builder   # install advandeb_kb
cp .env.example .env    # fill in required vars (see below)
python -m uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd app/frontend
npm install
npm run dev     # http://localhost:3000
npm run build
```

## Required Environment Variables (`backend/.env`)

These have no defaults and must be set:
```
JWT_SECRET_KEY=<random secret>
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/callback
MONGODB_URI=mongodb://localhost:27017
```

Optional (defaults shown):
```
MONGODB_DB_NAME=advandeb
MCP_SERVER_URL=http://localhost:8080
MCP_SERVER_ENABLED=true
OLLAMA_BASE_URL=http://localhost:11434
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
LOG_LEVEL=INFO
```

Settings are managed by `pydantic-settings` in `backend/app/core/config.py`. Add new settings there and access them via the `settings` singleton.

## Code Structure

```
backend/app/
├── main.py              # FastAPI app entry point, middleware, router registration
├── core/
│   ├── config.py        # Settings (pydantic-settings, reads .env)
│   ├── database.py      # MongoDB connection (Motor)
│   ├── auth.py          # JWT encode/decode utilities
│   └── dependencies.py  # Role-based FastAPI dependencies (require_admin, require_curator, etc.)
├── models/              # Pydantic models: user, document, fact, scenario, model
├── services/            # Business logic: user, document, fact, graph, chat, scenario, model
└── api/routes/          # FastAPI routers: auth, users, documents, facts, knowledge_graph, chat, scenarios, models

frontend/src/
├── views/               # Page components (Login, Home, Documents, Facts, Graph, Chat, Scenarios, Models)
├── stores/auth.ts       # Pinia auth store (token storage, user state)
├── utils/api.ts         # Axios client with JWT Authorization header interceptor
└── router/              # Vue Router config with auth guards
```

## Auth Flow

1. Frontend redirects to `GET /api/auth/google` → Google OAuth consent screen
2. Google redirects to `GET /api/auth/callback` → app exchanges code for tokens, issues JWT
3. Frontend stores JWT; `utils/api.ts` attaches it as `Authorization: Bearer <token>` on every request
4. `core/dependencies.py` provides FastAPI dependencies (`get_current_user`, role guards) used in route handlers

## User Roles

Enforced via dependencies in `core/dependencies.py`:
- **Administrator** — full access
- **Knowledge Curator** — knowledge creation, ingestion, agent access
- **Knowledge Explorator** — read-only browsing

## Calling MCP from Backend

The chat service (`services/chat_service.py`) is the integration point for MCP. Send JSON to `MCP_SERVER_URL`:
```python
{ "method": "tools/call", "params": { "name": "<tool>", "arguments": {...} } }
```
MCP is an internal service with no auth — do not add auth headers when calling it.

## Calling Knowledge Builder from Backend

Import KB as a local editable package:
```python
from advandeb_kb import KnowledgeService, IngestionService
from advandeb_kb.database.mongodb import get_database
```
Services in `services/` are the right place to call KB functions — not route handlers directly.
