# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AdvanDEB is a platform for knowledge management and modeling of bioenergetics/physiology using Dynamic Energy Budget (DEB) theory. This is a **monorepo** with the following top-level directories:

| Directory | Role |
|-----------|------|
| `docs/` | Architecture documentation and planning — no runnable code |
| `knowledge-builder/` | Python package (`advandeb_kb`) for knowledge operations |
| `mcp/` | Internal Rust/Axum MCP tool server for LLM agents |
| `app/` | Main GUI — the single user-facing application |

**Always read `docs/ARCHITECTURE-REVISION.md` first** when making cross-cutting decisions.

## Architecture

```
Users (Google OAuth)
        │
app/                         ← Single GUI entry point
  ├─ Vue 3 frontend
  ├─ FastAPI backend
  │   ├─ imports advandeb_kb (pip install -e ../knowledge-builder)
  │   └─ calls mcp/ (HTTP, no auth)
  └─ Google OAuth + JWT auth

mcp/ (Rust/Axum, port 8080)
  ├─ Exposes KB operations as MCP tools
  └─ Calls Ollama for LLM inference

Shared infrastructure:
  MongoDB :27017   Ollama :11434   Redis :6379 (Celery)
```

**Key constraint**: `knowledge-builder` is a library, not a standalone app. Its `dev-server/` subdirectory is a prototype FastAPI+Vue scaffold for standalone development; the real architecture has no UI in KB — all UI lives in `app/`.

## User Roles

Three roles in the platform (enforced by `app/` backend):
- **Administrator** — full system access
- **Knowledge Curator** — content creation, ingestion, agent access
- **Knowledge Explorator** — read-only browsing

## knowledge-builder

**Stack**: Python 3.11, Motor (async MongoDB), Pydantic v2, Ollama, Celery + Redis

**Install as editable package** (required before running `app/`):
```bash
cd knowledge-builder
pip install -e .
```

**Package layout:**
- `advandeb_kb/config/` — settings (env vars)
- `advandeb_kb/database/` — MongoDB Motor client
- `advandeb_kb/models/` — Pydantic data models (knowledge, ingestion, agents)
- `advandeb_kb/services/` — business logic (KnowledgeService, IngestionService, etc.)

**Dev server** (standalone FastAPI+Vue for prototyping):
```bash
cd knowledge-builder/dev-server
conda env create -f ../environment.yml   # first time
conda activate advandeb-knowledge-builder-backend
cp .env.example .env                     # configure MONGODB_URL, OLLAMA_BASE_URL
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

```bash
cd knowledge-builder/dev-server/frontend
npm install
npm run dev    # http://localhost:3000
npm run build  # validate after changes
```

**Env vars** (`dev-server/.env`):
```
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=advandeb_knowledge_builder_kb
OLLAMA_BASE_URL=http://localhost:11434
API_HOST=0.0.0.0
API_PORT=8000
MAX_FILE_SIZE=50000000
UPLOAD_DIR=uploads
```

**Code navigation:**
- Package public API: `knowledge-builder/advandeb_kb/__init__.py`
- Business logic: `knowledge-builder/advandeb_kb/services/`
- Data models: `knowledge-builder/advandeb_kb/models/`
- Dev-server routes: `knowledge-builder/dev-server/routers/`

## mcp

**Stack**: Rust 2021, Axum 0.7, Tokio, Reqwest, Serde

**Current state**: Early implementation — health check and `/chat` endpoint are working; full MCP tool suite is planned.

**Commands:**
```bash
cd mcp
cargo build
cargo run
cargo test
curl http://localhost:8080/health
```

**Configuration** (env vars, prefix `ADVANDEB_MCP_`):
```
ADVANDEB_MCP_BIND=0.0.0.0:8080
ADVANDEB_MCP_OLLAMA_HOST=http://localhost:11434
ADVANDEB_MCP_OLLAMA_MODEL=llama2
ADVANDEB_MCP_KB_API_BASE=http://localhost:8000
ADVANDEB_MCP_MA_API_BASE=http://localhost:9000
ADVANDEB_MCP_REQUEST_TIMEOUT_SECONDS=30
```

**Source layout:**
- `src/main.rs` — entry point
- `src/lib.rs` — Axum router and app state
- `src/config.rs` — settings from env
- `src/ollama.rs` — async Ollama HTTP client

**Design rule**: MCP has no authentication — it is an internal service called only by `app/`. `app/` handles all auth before forwarding requests.

## app

**Stack**: FastAPI + Python, Vue 3 + TypeScript + Vite, MongoDB, Google OAuth 2.0 + JWT

**Current state**: Scaffolded — structure is in place but most features are not yet implemented.

**Backend commands:**
```bash
cd app/backend
pip install -r requirements.txt
pip install -e ../../knowledge-builder   # install advandeb_kb
python -m uvicorn app.main:app --reload  # port 8000 by default
```

**Frontend commands:**
```bash
cd app/frontend
npm install
npm run dev    # http://localhost:3000
npm run build
```

**Backend layout:**
- `backend/app/core/` — config, database, auth (JWT), role dependencies
- `backend/app/models/` — user, document, fact, scenario, model Pydantic models
- `backend/app/services/` — user, document, fact, graph, chat, scenario, model services
- `backend/app/api/routes/` — auth (OAuth), users, documents, facts, knowledge_graph, chat, scenarios, models

**Frontend layout:**
- `frontend/src/views/` — HomeView, LoginView, DocumentsView, FactsView, GraphView, ChatView, ScenariosView, ModelsView
- `frontend/src/stores/auth.ts` — Pinia auth store
- `frontend/src/utils/api.ts` — Axios client with JWT interceptors

## Shared Infrastructure

Start all shared services before running any component:
```bash
docker run -d -p 27017:27017 --name mongodb mongo:7.0
ollama serve   # then: ollama pull llama2
redis-server   # only needed for KB batch ingestion
```

## Integration Contracts

- `app/backend` imports KB as a local editable package:
  ```python
  from advandeb_kb import KnowledgeService, IngestionService
  ```
- `app/backend` calls MCP via HTTP (no auth, internal only):
  ```json
  { "method": "tools/call", "params": { "name": "search_knowledge", "arguments": {...} } }
  ```
