# Running AdvanDEB

## Architecture

```
MongoDB :27017          ← shared database (advandeb + advandeb_knowledge_builder_kb)
Ollama  :11434          ← local LLM inference

App backend  :8400      ← FastAPI; serves /api/* AND the built Vue SPA from app/frontend/dist/
MCP Gateway  :8080      ← Rust binary; routes between app backend and specialized agents
Agents       :8081–8085 ← Python websocket agents (retrieval, graph, synthesis, planner, curator)
```

The app has **no nginx and no separate frontend server in production**.
The backend at `:8400` serves the compiled Vue SPA (`app/frontend/dist/`) directly via FastAPI's
`StaticFiles` + SPA fallback. All `/api/*` calls from the browser go to the same origin.

The Knowledge Builder (`/kb` route) is part of the main app backend.
Graph data lives in `advandeb_knowledge_builder_kb`; user/auth data lives in `advandeb`.

---

## Prerequisites

- `conda` (miniforge3) with environments:
  - `advandeb` — used by the app backend, KB dev-server, and all agents
- MongoDB running on `localhost:27017`
- Ollama running on `localhost:11434` with the configured model (`deepseek-r1:latest`)
- MCP gateway binary built: `cd mcp && cargo build --release`

---

## 1 — App Backend

Serves the API **and** the built frontend SPA.

```bash
conda activate advandeb
cd app/backend
pip install -r requirements.txt
pip install -e ../../knowledge-builder   # install advandeb_kb as editable package

# First time only — copy and fill in secrets:
cp .env.example .env
# Required fields to set in .env:
#   JWT_SECRET_KEY   — any random string
#   MONGODB_URI      — mongodb://localhost:27017  (default)
#   GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI  (optional, for OAuth)

uvicorn app.main:app --host 0.0.0.0 --port 8400 --reload
```

App is available at **http://localhost:8400**

The process is also managed by the systemd service file `scripts/advandeb.service`
(see "Systemd" section below).

---

## 2 — Frontend (development only)

Only needed when actively editing Vue/TypeScript. Not needed to run the app.

```bash
conda activate advandeb   # or use system node
cd app/frontend
npm install

# Dev server with hot-reload (proxies /api → :8400, /ws → :8400):
npm run dev               # available at http://localhost:5173

# Production build — output goes to app/frontend/dist/ and is served by the backend:
npm run build
```

After `npm run build`, restart (or `--reload`) the backend and the new UI is live at `:8400`.

---

## 3 — MCP Gateway + Agents

Needed for the chat/agent features in the app. Not required for graph browsing.

```bash
# Start everything (gateway + 5 agents + agent registration):
./scripts/start_all.sh

# Stop everything:
./scripts/stop_all.sh
```

Logs go to `logs/`.

Individual service URLs after start:
- MCP Gateway health: http://localhost:8080/health
- Registered agents:  http://localhost:8080/agents

---

## Systemd (production / autostart)

Service files are in `scripts/`. Install them with:

```bash
sudo cp scripts/advandeb.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable advandeb
sudo systemctl start  advandeb
```

Check status:

```bash
sudo systemctl status advandeb
journalctl -u advandeb -f
```

---

## Port Summary

| Port  | Service                          | Started by               |
|-------|----------------------------------|--------------------------|
| 8400  | App backend + Vue SPA            | uvicorn / advandeb.service |
| 8080  | MCP Gateway (Rust)               | start_all.sh             |
| 8081  | retrieval_agent                  | start_all.sh             |
| 8082  | graph_explorer_agent             | start_all.sh             |
| 8083  | synthesis_agent                  | start_all.sh             |
| 8084  | query_planner_agent              | start_all.sh             |
| 8085  | curator_agent                    | start_all.sh             |
| 27017 | MongoDB                          | system / mongod          |
| 11434 | Ollama                           | system / ollama serve    |

---

## Common Issues

**`ModuleNotFoundError: No module named 'advandeb_kb'`**
Run `pip install -e ../../knowledge-builder` from `app/backend/` inside the `advandeb` conda env.

**Graph view is empty / 401 errors in browser console**
The app is at `:8400`. Make sure you are not trying to reach it through port 80 (nginx is not used).

**Graph view is empty but no errors**
Schemas may not be seeded yet. Go to `/kb` in the app, open the schema dropdown — if empty,
the seed endpoint will be called automatically. If graph data is missing, use the rebuild button
in the KB drawer to rebuild the desired schema.

**Changes to Vue components not visible**
Run `npm run build` in `app/frontend/`, then restart (or wait for `--reload`) the backend at `:8400`.
The backend serves `app/frontend/dist/` — the dev server at `:5173` is separate.
