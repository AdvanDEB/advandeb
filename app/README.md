# AdvanDEB — App

**Status**: Internal tool — under active development.
**Version**: 0.1.0

> Note: this component was historically called the "Modeling Assistant", and
> some strings in the code still say so. It is the AdvanDEB application
> itself. Its first real modeling feature is the tDEB simulator at `/models`.
> See `../docs/SYSTEM-OVERVIEW.md`.

---

## Overview

The AdvanDEB app is the web interface to a curated knowledge graph for Dynamic
Energy Budget (DEB) biology. It combines:
- chat with citations;
- knowledge exploration and curation;
- a tDEB model simulator;
- expert elicitation.

There is one FastAPI backend and one Vue 3 frontend.

### Key Features

**Chat with citations** (`/chat`)
- WebSocket streaming (`/ws/chat/{session_id}`), with an agent-activity panel
- **Shared default model:** NVIDIA Nemotron on one operator key, rate-limited
  across all users
- **Bring your own key:** Anthropic, OpenAI, Gemini, GitHub Models (including
  "Connect with GitHub"), NVIDIA. Keys are encrypted at rest.
- KAG pipeline with an EvidenceRegistry. Citation markers: `[n]` chunks, `[G]`
  graph facts, `[SF]` stylized facts, `[D]` AdvanDEB's own docs.
  See `../docs/SYSTEM-OVERVIEW.md` §4a.
- Sessions: rename, per-session instructions, prompt library, suggested
  follow-ups, answer feedback

**Knowledge exploration**
- Documents (`/documents`), with processing status and user flags
- Facts (`/facts`): stylized facts, KB facts, user fact suggestions
- Knowledge Builder (`/kb`, curators and admins):
  - a Cosmograph WebGL canvas over seven graph schemas;
  - ingestion, database inspection, KG builder (document→taxon links);
  - suggestions and review queues

**Provenance**
- Citation trails: Answer → Facts → Chunks → Documents, with expandable chunk
  context. `[D]` citations resolve to the in-app documentation.
- Trails are **reconstructed on read**, not persisted. A historical answer's
  evidence chain cannot be audited after the fact. See
  `../docs/STORAGE-CONTRACT.md` §5.

**tDEB simulator and model library** (`/models`, `/models/:id`)
- Per-user transport-network DEB models and editable equations
- Changes saved as you edit
- Simulation on the backend (SciPy `solve_ivp`)
- Templates published by curators

**Expert elicitation** (`/elicitation`, public `/elicitation/join`, admin `/admin/experts`)
- Stylized-fact judgment queue with a calibration gate
- Panel and contributor tiers
- Expert-asserted DOI references
- See `../docs/ELICITATION.md`.

**Administration** (`/admin/users`, `/admin/experts`)
- User and role management
- Consented chat review, with an access audit log
- Expert enrolment review and capability grants

---

## Architecture

```
app/
├── backend/               # FastAPI backend (serves /api/*, /ws/* and, locally, the built SPA)
│   ├── app/
│   │   ├── api/routes/   # API endpoints (incl. kb/ for the Knowledge Builder)
│   │   ├── services/     # Business logic (chat, BYOK/KAG, elicitation, provenance, …)
│   │   ├── models/       # Pydantic models
│   │   ├── core/         # Config, auth, roles/capabilities, crypto, dbguard
│   │   ├── kb/           # Ingestion pipeline (FastAPI background tasks)
│   │   ├── tdeb/         # tDEB simulator: network model, equations, solver
│   │   └── data/         # platform_docs.json — in-app docs, citable in chat as [D]
│   ├── tests/
│   └── requirements.txt
│
├── frontend/             # Vue 3 + TypeScript frontend
│   ├── src/
│   │   ├── views/       # Page components
│   │   ├── components/  # Reusable components
│   │   ├── stores/      # Pinia state management
│   │   ├── utils/       # API client, helpers
│   │   ├── router/      # Vue Router config
│   │   └── tests/       # vitest unit tests
│   ├── tests/e2e/       # Playwright specs
│   └── package.json
│
├── DEPLOYMENT.md              # HISTORICAL — see ../RUNNING.md
├── MONITORING.md              # HISTORICAL / proposal
└── README.md                  # This file
```

---

## Quick Start

### Development Mode

```bash
# From the repo root.
# Terminal 1: Backend (serves /api/* on :8400)
cd app/backend
cp .env.example .env  # Configure environment (see below)
pip install -r requirements.txt
pip install -e ../../knowledge-builder
uvicorn app.main:app --reload --port 8400

# Terminal 2: Frontend dev server (Vite, hot-reload on :5173), from the repo root
cd app/frontend
npm install
npm run dev
```

Access the dev UI at **http://localhost:5173**. Vite proxies `/api/*` and
`/ws/*` to the backend on :8400.

### Production Mode

The built SPA lives in `frontend/dist/`:
- **Locally**, the FastAPI backend serves it alongside the API on `:8400`.
- **On advandeb.com**, a Cloudflare Tunnel reaches nginx on `127.0.0.1:8200`.
  nginx serves `dist/` from disk and proxies `/api/` and `/ws/` to `:8400`.

```bash
# From the repo root. Build the frontend (output goes to app/frontend/dist/)
cd app/frontend
npm run build

# Run the backend; it will mount and serve dist/
cd ../backend
uvicorn app.main:app --port 8400
```

For the canonical ops instructions (systemd units, service management,
environment), see [`RUNNING.md`](../RUNNING.md) at the repo root.

---

## Environment Configuration

### Backend (.env)

Start from `backend/.env.example`. The full variable table, including what
breaks without each one, is in [`RUNNING.md`](../RUNNING.md).

The minimum for a working local app:

```env
JWT_SECRET_KEY=<random, ≥32 chars>
ENVIRONMENT=development
MONGODB_URI=mongodb://localhost:27017
ARANGO_USERNAME=<user>
ARANGO_PASSWORD=<password>
```

Add these for chat:

```env
DEFAULT_CHAT_API_KEY=<NVIDIA API key>   # shared default model; not in .env.example
LLM_KEY_ENCRYPTION_KEY=<Fernet key>     # required to save BYOK keys
```

Google OAuth variables are optional; the button is hidden in the UI.

**`MONGODB_DB_NAME` defaults to `advandeb`, which is the production
database.** Anything that writes must use a scratch name; see RUNNING.md.

---

## Development

### Running Tests

**Frontend** (vitest), from the repo root:
```bash
cd app/frontend
npm test            # vitest run
npm run test:watch
```

`npm test` currently also picks up the Playwright specs in `tests/e2e/`, and
those two files fail (C1 in `../docs/PLAN-2026-08-26.md`). The 48 unit tests
pass. Run the Playwright specs with `npm run test:e2e`, against a running app.

**Backend**, from the repo root:
```bash
cd app/backend && JWT_SECRET_KEY=local-test-secret-key-at-least-32-chars ENVIRONMENT=development MONGODB_URI=mongodb://127.0.0.1:1 python -m pytest -q
```

Use `python -m pytest`; plain `pytest` cannot import `app.*`. The tests mock
MongoDB, and the unreachable URI makes sure nothing reaches a live database.
`tests/verify_*.py` are scripts, not pytest modules. They write to MongoDB, so
run them only against a guarded scratch database.

### Building

```bash
cd app/frontend
npm run build       # vue-tsc type-check, then vite build → dist/
```

### Code Quality

`black`, `isort` and `mypy` are in `backend/requirements.txt`; run them from
`app/backend` against `app/`. CI does not enforce them. The frontend `lint`
and `format` scripts exist in `package.json`, but there is no ESLint
configuration in the repo, so `npm run lint` does not do anything useful yet.

---

## Deployment

See [`RUNNING.md`](../RUNNING.md) for the canonical ops instructions.
[DEPLOYMENT.md](DEPLOYMENT.md) is historical.

---

## Monitoring

Sentry is not integrated, and the backend has no metrics endpoint. Use
`GET /api/health`. Prometheus/Grafana configuration for the gateway and host
is under `../monitoring/`. [MONITORING.md](MONITORING.md) is a proposal, not
a description.

---

## API Documentation

When running the backend, interactive API docs are available at:
- **Swagger UI**: http://localhost:8400/docs
- **ReDoc**: http://localhost:8400/redoc

### Key Endpoints

Every router is mounted in `backend/app/main.py`. The ones most often needed:

**Authentication** (`/api/auth`):
- `POST /login` — email + password → access and refresh tokens
- `POST /token` — OAuth2 password form (for the Swagger "Authorize" button)
- `POST /refresh` — new access token from a refresh token
- `POST /logout` — revoke the refresh token
- `GET /config` — which sign-in methods are enabled
- `POST /google` — Google sign-in (hidden in the UI)

There is no self-registration endpoint. Accounts are created by an
administrator (`POST /api/users/`) or by approving an elicitation enrolment.

**Users** (`/api/users`):
- `GET` / `PUT /me`, `PUT /me/password`
- admin: list, create, roles, status, reset password, consented chat review

**BYOK keys** (`/api/users/me/llm-keys`):
- `GET /providers`
- `GET` / `POST ""` — list or add a key
- `POST /{key}/test`, `DELETE /{key}`, `GET /{key}/models`
- `POST /oauth/github/start`, `POST /oauth/github/poll` — GitHub device flow

**Chat** (`/api/chat`, `/ws`):
- `WS /ws/chat/{session_id}` — the streaming chat path the UI uses
- `GET /api/chat/default-model`
- `GET /api/chat/sessions`, `GET` / `PUT` / `DELETE /api/chat/sessions/{id}`
- `PUT /sessions/{id}/llm`, `/rename`, `/system-prompt`
- `POST /api/chat/messages/{id}/feedback`
- `POST /api/chat/` — REST fallback via the MCP gateway; not used by the UI

**Provenance** (`/api/graph`):
- `GET /provenance/{citation_id}`
- `GET /chunk/{chunk_id}/context`

**Documents and facts**:
- `/api/documents` — list, get, upload, approve, delete
- `/api/facts` — facts and stylized facts, with review

**Knowledge Builder** (`/api/kb/*`, curators):
- `viz` — graph schemas, artifacts, rebuild, expansion
- `ingestion`
- `db` — collections, review queues, reset
- `kg` — document→taxon linking
- `documents`, `facts`, `stylized-facts`, `fs`, `agents`

**tDEB** (`/api/tdeb`):
- `GET /templates`, `GET /published`
- models CRUD; nodes and edges
- `POST /models/{id}/simulate`, `WS /api/tdeb/ws/simulate/{id}`
- `POST` / `DELETE /models/{id}/publish` (curator)
- equations: get, update, reset, validate

**Elicitation** (`/api/elicitation`, `/api/enrolment`): see
`../docs/ELICITATION.md` §9.

**Health**: `GET /api/health` (canonical), `GET /health`, `GET /api/info`.

---

## Tech Stack

### Frontend
- **Framework**: Vue 3 (Composition API), TypeScript, Vite
- **State / routing**: Pinia, Vue Router
- **UI**: Element Plus and Tailwind CSS
- **Graph**: Cosmograph (WebGL)
- **Markdown**: marked + highlight.js, sanitised with DOMPurify
- **Testing**: Vitest (unit), Playwright (e2e)

### Backend
- **Framework**: FastAPI, Python 3.11
- **Datastores**: ArangoDB (canonical knowledge), ChromaDB (vectors),
  MongoDB via Motor (application state), graph artifacts as gzipped JSON on
  disk. See `../docs/STORAGE-CONTRACT.md`.
- **LLMs**: external providers for chat (NVIDIA default; BYOK Anthropic,
  OpenAI, Gemini, GitHub Models, NVIDIA); local Ollama for agents,
  extraction and follow-ups
- **Simulation**: SciPy (`solve_ivp`) for tDEB
- **Authentication**: JWT + native password; Google OAuth implemented but
  currently hidden in the UI; GitHub OAuth device flow for GitHub Models
- **Testing**: pytest + pytest-asyncio

### Infrastructure
- **Web server**: uvicorn on :8400. In production it sits behind Cloudflare
  Tunnel → nginx :8200, and nginx serves the SPA.
- **Process management**: systemd. `advandeb.target` pulls in
  `advandeb.service` (backend) and `advandeb-stack.service` (MCP gateway + 6
  agents). The units are in `../scripts/systemd/`.
- **Monitoring**: see above.

---

## Project Timeline

See [`docs/ROADMAP.md`](../docs/ROADMAP.md) for current phase status and outstanding work.

---

## Integration

### With Knowledge Builder
- Imports the `advandeb_kb` package (`pip install -e ../../knowledge-builder`)
- Shares the MongoDB application database (`advandeb`)
- Reads canonical knowledge from ArangoDB, via the KB package, and serves
  graph views as prebuilt artifacts built from ArangoDB
- Note: a second Mongo database, `advandeb_knowledge_builder_kb`, is a
  transitional Mongo→Arango migration remnant. Do not add new writers to it.

### With the agents and the MCP gateway
- The chat path talks to `chatbot_agent` (`CHATBOT_AGENT_WS`, :8086) and
  `retrieval_agent` (`RETRIEVAL_AGENT_WS`, :8081) **directly**
- The MCP gateway (:8080) is used only by the REST fallback `POST /api/chat/`
- No authentication on either (internal, loopback-only)

---

## User Roles and Capabilities

Defined in `backend/app/core/dependencies.py`:

- **Administrator**: full access, user management, expert management
- **Knowledge Curator**: create, edit and review knowledge; Knowledge Builder;
  publish tDEB templates
- **Knowledge Explorator**: the default role on account creation; chat,
  read access, own tDEB models
- **External Contributor**: elicitation and settings only; no documents,
  chat, KB, graph or models

Roles are enforced with `require_admin` and `require_curator`.

**Capabilities** are enforced with `require_capability(...)`. One is in use:
`sf_elicitation`, which gates every elicitation endpoint. An administrator
grants it, or enrolment approval does. Curators and external contributors
pass the check by role. The older capability design (Knowledge Creation,
Agent Access, Analytics Access, Reviewer Status) remains unimplemented.

**Anonymous access** is limited to:
- the landing page;
- login;
- the elicitation enrolment form (`POST /api/enrolment/request`,
  rate-limited).

Everything that reads knowledge requires an account.

---

## Security

- JWT-based authentication with enforced `type` claims (access vs refresh).
  Both tokens are currently held in `localStorage` (C14 in the plan).
- Refresh-token revocation on logout (`revoked_tokens`, TTL-indexed)
- `slowapi` rate limiting on auth endpoints and on public enrolment
- Constant-time login (bcrypt against a dummy hash on user-not-found)
- `JWT_SECRET_KEY` validator rejects unset/short/example secrets outside development
- BYOK keys Fernet-encrypted at rest (`LLM_KEY_ENCRYPTION_KEY`); only the last
  four characters are ever shown back
- Object-level authorization on user-owned resources (`a985b7a`)
- CORS configuration and security headers

---

## Troubleshooting

### Frontend not loading
```bash
# In dev: make sure the Vite dev server is running on :5173 (from the repo root)
cd app/frontend && npm run dev

# Locally: the FastAPI backend serves frontend/dist/ — make sure you ran
#   npm run build
# and that the backend is up on :8400.
# In production nginx serves dist/ from disk; a new build is live immediately,
# but backend changes need a restart of advandeb.service.
```

### Backend connection errors
```bash
# Check backend logs from uvicorn (or journalctl -u advandeb)
# Verify MongoDB is running:
mongosh --eval "db.adminCommand('ping')"
```

### WebSocket connection failures
- Verify the backend is reachable on :8400
- Check the backend WebSocket registration in `main.py`
- In dev, confirm the Vite proxy forwards `/ws/*` to the backend

More failure modes: [`RUNNING.md`](../RUNNING.md) → Common Issues.

---

## Resources

- [Roadmap](../docs/ROADMAP.md)
- [System overview](../docs/SYSTEM-OVERVIEW.md)
- [Running the app](../RUNNING.md)
- [Storage contract](../docs/STORAGE-CONTRACT.md)
- [Expert elicitation](../docs/ELICITATION.md)
- [Vue 3 Docs](https://vuejs.org/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)

---

## License

No licence has been granted; all rights reserved. See the root
[`README.md`](../README.md#licensing).

---

**Last Updated**: 2026-10-28
