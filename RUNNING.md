# Running AdvanDEB

> **Reconciled 2026-08-26** against the running system. The previous revision
> listed only MongoDB and Ollama as datastores; following it exactly left the
> retrieval stack non-functional, because **ArangoDB and ChromaDB were missing
> from both the diagram and the prerequisites.**

## Architecture

```
MongoDB  :27017         ← application store (advandeb) + transitional KB store
ArangoDB :8529          ← canonical knowledge store (advandeb_kb)  [loopback]
ChromaDB  (filesystem)  ← canonical vector store, data/chromadb (~17 GB)
Ollama   :11434         ← local LLM inference                      [loopback]

App backend  :8400      ← FastAPI; serves /api/* AND the built Vue SPA from app/frontend/dist/
MCP Gateway  :8080      ← Rust binary; routes between app backend and agents  [loopback]
Agents       :8081–8086 ← 6 Python websocket agents
                          (retrieval, graph_explorer, synthesis, query_planner,
                           curator, chatbot)
                          HTTP health endpoints at port + 100 → :8181–:8186
```

The app has **no nginx and no separate frontend server in production**.
The backend at `:8400` serves the compiled Vue SPA (`app/frontend/dist/`) directly via FastAPI's
`StaticFiles` + SPA fallback. All `/api/*` calls from the browser go to the same origin.

The Knowledge Builder (`/kb` route) is part of the main app backend.

### Which store holds what

Short version — the full contract is in `docs/STORAGE-CONTRACT.md`:

- **ArangoDB `advandeb_kb`** — canonical: documents, chunks, facts, stylized
  facts, taxa, and the graph edges between them.
- **ChromaDB** — canonical: chunk embeddings. Semantic retrieval reads it directly.
- **MongoDB `advandeb`** — canonical: users, auth, chat, LLM keys, audit logs.
  Also holds the *materialized* graph (`graph_nodes` / `graph_edges`) that the
  frontend renders.
- **MongoDB `advandeb_knowledge_builder_kb`** — **transitional**, a
  Mongo→Arango migration remnant that still backs ingestion workflow state,
  visualization artifacts, and user submissions. Do not add new writers.

---

## Prerequisites

- `conda` (miniforge3) with environment `advandeb` — used by the app backend,
  KB dev-server, and all agents
- **MongoDB** on `localhost:27017`
- **ArangoDB** on `localhost:8529`, with the `advandeb_kb` database and a user
  that can read and write it
- **ChromaDB** — no server process; on-disk at `data/chromadb`. Budget **~20 GB
  free disk**; the current store is 17 GB.
- **Ollama** on `localhost:11434` with the configured model (`deepseek-r1:latest`)
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
uvicorn app.main:app --host 0.0.0.0 --port 8400 --reload
```

Required fields in `.env`:

| Variable | Notes |
|---|---|
| `JWT_SECRET_KEY` | Any random string. **Must be ≥32 chars and not the example value** when `ENVIRONMENT != development` — `Settings` refuses to construct otherwise. |
| `MONGODB_URI` | default `mongodb://localhost:27017` |
| `MONGODB_DB_NAME` | default `advandeb` |
| `KB_DB_NAME` | default `advandeb_knowledge_builder_kb` (transitional) |
| `ARANGO_URL` | default `http://localhost:8529` |
| `ARANGO_DB_NAME` | default `advandeb_kb` |
| `ARANGO_USERNAME` / `ARANGO_PASSWORD` | **required** — without these, retrieval, graph views, and provenance all fail |
| `CHROMA_COLLECTION` | vector collection name |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | optional; the Google sign-in button is currently hidden in the UI |

App is available at **http://localhost:8400**

The process is also managed by the systemd unit `scripts/advandeb.service`
(see "Systemd" below).

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
# Start everything (gateway + 6 agents + agent registration):
./scripts/start_all.sh

# Stop everything:
./scripts/stop_all.sh
```

Logs go to `logs/`, one file per agent.

- MCP Gateway health: http://localhost:8080/health
- Registered agents:  http://localhost:8080/agents

`retrieval_agent` loads an embedding model on boot and can take up to 90 s to
report healthy. That is normal.

---

## Systemd (production / autostart)

Three units, installed from `scripts/`:

| Unit | Role |
|---|---|
| `advandeb.target` | The full application — pulls in both units below |
| `advandeb.service` | FastAPI backend + Vue SPA on `:8400` |
| `advandeb-stack.service` | MCP gateway + the 6 agents |

```bash
sudo cp scripts/advandeb.service scripts/advandeb-stack.service scripts/advandeb.target /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable advandeb.target
sudo systemctl start  advandeb.target
```

Check status:

```bash
systemctl status advandeb.target
journalctl -u advandeb -f
journalctl -u advandeb-stack -f
```

---

## Port Summary

| Port  | Service                          | Bind      | Started by                 |
|-------|----------------------------------|-----------|----------------------------|
| 8400  | App backend + Vue SPA            | `0.0.0.0` | uvicorn / advandeb.service |
| 8080  | MCP Gateway (Rust)               | loopback  | start_all.sh / stack       |
| 8081  | retrieval_agent                  | loopback  | start_all.sh / stack       |
| 8082  | graph_explorer_agent             | loopback  | start_all.sh / stack       |
| 8083  | synthesis_agent                  | loopback  | start_all.sh / stack       |
| 8084  | query_planner_agent              | loopback  | start_all.sh / stack       |
| 8085  | curator_agent                    | loopback  | start_all.sh / stack       |
| 8086  | chatbot_agent                    | loopback  | start_all.sh / stack       |
| 8181–8186 | per-agent HTTP health        | loopback  | the agents themselves      |
| 8529  | ArangoDB                         | loopback  | system / arangod           |
| 27017 | MongoDB                          | `0.0.0.0` | system / mongod            |
| 11434 | Ollama                           | loopback  | system / ollama serve      |

---

## Health checks

```bash
curl http://localhost:8400/api/health     # canonical — returns JSON incl. a Mongo ping
curl http://localhost:8080/health         # MCP gateway
```

`/api/health` is the endpoint to point monitors at. `/health` still exists and
returns the same payload, but it is shadowed by the SPA fallback in setups that
route non-`/api` paths to the Vue bundle.

---

## Common Issues

**`ModuleNotFoundError: No module named 'advandeb_kb'`**
Run `pip install -e ../../knowledge-builder` from `app/backend/` inside the `advandeb` conda env.

**Backend refuses to start with a `JWT_SECRET_KEY` error**
`Settings` rejects an unset, short (<32 chars), or example secret when
`ENVIRONMENT != development`. Set a real one, or set `ENVIRONMENT=development`
for local work.

**Retrieval returns nothing / chat cites nothing / provenance panel is empty**
Almost always ArangoDB. Check that `arangod` is up on `:8529` and that
`ARANGO_USERNAME` / `ARANGO_PASSWORD` are set in `app/backend/.env` — a 401 from
Arango surfaces as empty results rather than an obvious error.

**Semantic search is weak but keyword search works**
ChromaDB side of the hybrid retrieval is degraded. Check `data/chromadb` exists
and has free disk beneath it.

**Graph view is empty / 401 errors in browser console**
The app is at `:8400`. Make sure you are not trying to reach it through port 80 (nginx is not used).

**Graph view is empty but no errors**
Schemas may not be seeded yet. Go to `/kb` in the app, open the schema dropdown — if empty,
the seed endpoint will be called automatically. If graph data is missing, use the rebuild button
in the KB drawer to rebuild the desired schema.

**Graph view is stale after ingesting or chatting**
Expected. Materialized graphs are rebuilt by `GraphRebuildQueue` with a 5 s
settle delay and a **120 s floor** between rebuilds of the same schema. The
floor is deliberate — removing it drives back-to-back full-graph rebuilds that
pin a CPU and grow RSS. See `docs/STORAGE-CONTRACT.md` §4.

**`physiological_process` graph is always empty**
Known. The schema is registered but nothing ever marks it dirty, and its source
relation collections (`sf_sf_relations`, `sf_taxon_relations`) do not exist. See
`docs/knowledge_graph_scheme_descriptions.md`.

**Changes to Vue components not visible**
Run `npm run build` in `app/frontend/`, then restart (or wait for `--reload`) the backend at `:8400`.
The backend serves `app/frontend/dist/` — the dev server at `:5173` is separate.
