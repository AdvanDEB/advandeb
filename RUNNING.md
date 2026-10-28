# Running AdvanDEB

> **Reconciled 2026-08-26** against the running system; **updated 2026-10-28**
> for:
> - the production edge (Cloudflare Tunnel → nginx);
> - the default-chat and BYOK environment variables;
> - the chat request path;
> - the systemd unit paths;
> - the MCP gateway build, which is broken at HEAD.
>
> The 2026-08-26 revision fixed an earlier omission: ArangoDB and ChromaDB
> were missing from both the diagram and the prerequisites, so following the
> doc left retrieval non-functional.

## Architecture

```
MongoDB  :27017         ← application store (advandeb) + transitional KB store   [all interfaces]
ArangoDB :8529          ← canonical knowledge store (advandeb_kb)                [loopback]
ChromaDB  (filesystem)  ← canonical vector store, data/chromadb (~17 GB)
Ollama   :11434         ← local LLMs: agents, extraction, reranking, follow-ups  [loopback]

App backend  :8400      ← FastAPI; serves /api/* and /ws/*, and the built Vue SPA when hit directly
MCP Gateway  :8080      ← Rust binary; only the REST fallback POST /api/chat/ uses it  [loopback]
Agents       :8081–8086 ← 6 Python websocket agents
                          (retrieval, graph_explorer, synthesis, query_planner,
                           curator, chatbot)
                          HTTP health endpoints at port + 100 → :8181–:8186

External: NVIDIA API (default chat model), BYOK providers, OpenAlex/Crossref.
```

**Production edge.** advandeb.com → Cloudflare Tunnel → nginx on
`127.0.0.1:8200` (site `/etc/nginx/sites-enabled/advandeb`). nginx serves the
SPA straight from `app/frontend/dist/` on disk and proxies `/api/` and `/ws/`
to `:8400`. Neither the tunnel nor the nginx config is in this repository.

**Locally there is no proxy.** The backend serves `app/frontend/dist/` itself,
via `StaticFiles` and an SPA fallback, so everything is same-origin on `:8400`.

**Chat path.** The backend calls the agents directly. The default and BYOK
paths use the retrieval agent (`RETRIEVAL_AGENT_WS`, `:8081`); the ReAct path
uses the chatbot agent (`CHATBOT_AGENT_WS`, `:8086`). The gateway is not
involved. See `docs/SYSTEM-OVERVIEW.md` §4a.

The Knowledge Builder (`/kb` route) is part of the main app backend.

### Which store holds what

Short version — the full contract is in `docs/STORAGE-CONTRACT.md`:

- **ArangoDB `advandeb_kb`** — canonical: documents, chunks, facts, stylized
  facts, taxa, and the graph edges between them.
- **ChromaDB** — canonical: chunk embeddings. Semantic retrieval reads it directly.
- **MongoDB `advandeb`** — canonical: users, auth, chat, LLM keys, audit
  logs, tDEB models, elicitation.
- **MongoDB `advandeb_knowledge_builder_kb`** — **transitional**, a
  Mongo→Arango migration remnant. It still backs ingestion workflow state,
  graph-artifact metadata (`graph_artifact_meta`) and user submissions. Do not
  add new writers.
- **Graph artifacts** — the graphs the frontend renders. They are gzipped JSON
  files under `GRAPH_ARTIFACT_DIR` (default `data/graph_artifacts`), built from
  ArangoDB and safe to delete and rebuild. The old Mongo `graph_nodes` /
  `graph_edges` collections are no longer used.

---

## Prerequisites

- `conda` (miniforge3) with environment `advandeb` — used by the app backend
  and all agents
- **MongoDB** on `localhost:27017`. On the production host it runs in a
  container defined by another project's (cadapti) Docker Compose, bound to all
  interfaces.
- **ArangoDB** on `localhost:8529`, with the `advandeb_kb` database and a user
  that can read and write it
- **ChromaDB** — no server process; on-disk at `data/chromadb`. Budget **~20 GB
  free disk**; the current store is 17 GB.
- **Ollama** on `localhost:11434` with the configured models:
  - `deepseek-r1:latest` (`OLLAMA_MODEL`, `CHAT_ANSWER_MODEL`, `CHAT_VERIFY_MODEL`);
  - `gemma3:latest` (`CHAT_GRAPH_MODEL`, `CHAT_FOLLOWUP_MODEL`).
- **An NVIDIA API key** for the shared default chat model
  (`DEFAULT_CHAT_API_KEY`). Without one, users without their own key fall
  through to the local agent path.
- The MCP gateway binary, built with `cd mcp && cargo build --release`.
  **This does not compile at HEAD** (2026-10-28): `src/lib.rs` uses
  `tokio::signal`, but `mcp/Cargo.toml` does not enable tokio's `signal`
  feature. It is tracked under C1 in the plan. Until it is fixed, see §3 for
  running without the gateway.

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

`.env` fields that matter. Settings live in `app/backend/app/core/config.py`.
Chat-pipeline `CHAT_*` variables are read by `advandeb_kb.config.settings`.

| Variable | Notes |
|---|---|
| `JWT_SECRET_KEY` | **Required.** Any random string. Must be ≥32 chars and not the example value when `ENVIRONMENT != development`; otherwise `Settings` refuses to construct. |
| `MONGODB_URI` | **Required** (no default in `Settings`). Normally `mongodb://localhost:27017`. |
| `MONGODB_DB_NAME` | default `advandeb`. **This is the production database name**; see "Scratch databases" below. |
| `KB_DB_NAME` | default `advandeb_knowledge_builder_kb` (transitional) |
| `ARANGO_URL` | default `http://localhost:8529` |
| `ARANGO_DB_NAME` | default `advandeb_kb` |
| `ARANGO_USERNAME` / `ARANGO_PASSWORD` | **Required in practice.** Without them, retrieval, graph views and provenance all fail. |
| `CHROMA_COLLECTION` | vector collection name (default `advandeb_chunks`) |
| `MCP_SERVER_ENABLED` | default `true`. **Every chat path requires it**, despite the name; with it off, chat answers "MCP server is not enabled." |
| `CHATBOT_AGENT_WS` / `RETRIEVAL_AGENT_WS` | defaults `ws://localhost:8086` / `ws://localhost:8081` |
| `DEFAULT_CHAT_API_KEY` | The shared key used for every session without a BYOK key. **Not in `.env.example`; add it by hand.** If unset, those sessions go to the chatbot agent and local Ollama models. |
| `DEFAULT_CHAT_PROVIDER` / `DEFAULT_CHAT_MODEL` | defaults `nvidia` / `nvidia/nemotron-3-ultra-550b-a55b`; must match what the key can reach |
| `DEFAULT_CHAT_RPM` | default `40` turns/min, **shared across all users** of the default key. Keep it within the key's rate-limit tier. |
| `LLM_KEY_ENCRYPTION_KEY` | Fernet key that encrypts users' BYOK keys at rest. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. If unset, the app boots but saving a BYOK key fails with HTTP 500. If set to anything but a valid 44-char Fernet key, the app refuses to start. **Never rotate it without re-encrypting the stored keys** — every saved key would become unreadable. |
| `GITHUB_OAUTH_CLIENT_ID` | optional; enables "Connect with GitHub" (device flow) for GitHub Models. Unset hides it. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | optional; the Google sign-in button is currently hidden in the UI |
| `ELICITATION_HUMAN_PANEL_SIZE` / `ELICITATION_COMPARISON_EVERY` / `ELICITATION_EVIDENCE_PASSAGES` | optional, read from the environment directly; defaults `5` / `25` / `18`. See `docs/ELICITATION.md` §8. |

**Scratch databases.** Any script or test that writes to MongoDB must point
`MONGODB_DB_NAME` at a database whose name says it is scratch. Set it
explicitly; never rely on `os.environ.setdefault`.
`app/backend/app/core/dbguard.py` enforces this for code that uses it. A
`setdefault` after `.env` had loaded once dropped a production collection
(see `docs/STORAGE-CONTRACT.md` §2a).

App is available at **http://localhost:8400**

In production the process is managed by the systemd unit
`scripts/systemd/advandeb.service` (see "Systemd" below).

---

## 2 — Frontend (development only)

Only needed when actively editing Vue/TypeScript. Not needed to run the app.

```bash
conda activate advandeb   # or use system node
cd app/frontend
npm install

# Dev server with hot-reload (proxies /api → :8400, /ws → :8400):
npm run dev               # available at http://localhost:5173

# Production build — output goes to app/frontend/dist/ (served by nginx in production, by the backend locally):
npm run build
```

After `npm run build`, the new UI is live:
- **in production at once**, because nginx serves `dist/` from disk. The
  backend does not reload, so a frontend that expects new API routes will 404
  until the backend restarts.
- **locally on `:8400`** on the next request. The backend serves `dist/` too.

---

## 3 — MCP Gateway + Agents

Needed for chat. Not required for graph browsing, the tDEB simulator or
elicitation.

```bash
# From the repo root. Start everything (gateway + 6 agents + agent registration):
./scripts/start_all.sh

# Stop everything:
./scripts/stop_all.sh
```

Logs go to `logs/`, one file per agent.

- MCP Gateway health: http://localhost:8080/health
- Registered agents:  http://localhost:8080/agents

**The registry is in memory.** It is filled by
`scripts/register_all_agents.sh`, which `start_all.sh` and `start_stack.sh`
call. A gateway restarted on its own comes back with `{"agents":[]}`, which is
what production reported on 2026-10-28. That is harmless for the UI, because
the chat paths do not use the gateway.

`retrieval_agent` loads an embedding model on boot and can take up to 90 s to
report healthy. That is normal.

**Without the gateway binary.** It does not build at HEAD (see
Prerequisites), and `start_all.sh` exits if the binary is missing. In that
case, start the five tool agents on their own:

```bash
cd knowledge-builder && python scripts/start_agents.py
```

Stop them with `python scripts/start_agents.py --stop`.

This covers the default and BYOK chat paths, which need only the retrieval
agent; `--agents retrieval` starts just that one. It does **not** start
`chatbot_agent` (`:8086`), so the ReAct path stays unavailable.

---

## Systemd (production / autostart)

Three units, installed from **`scripts/systemd/`**:

| Unit | Role |
|---|---|
| `advandeb.target` | The full application — pulls in both units below |
| `advandeb.service` | FastAPI backend on `:8400` (`EnvironmentFile=app/backend/.env`) |
| `advandeb-stack.service` | MCP gateway + the 6 agents (`scripts/start_stack.sh`) |

```bash
sudo cp scripts/systemd/advandeb.service scripts/systemd/advandeb-stack.service scripts/systemd/advandeb.target /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable advandeb.target
sudo systemctl start  advandeb.target
```

**Use the `scripts/systemd/` copies.** The older copies of
`advandeb.service` and `advandeb-stack.service` directly under `scripts/` lack
`PartOf=advandeb.target`, so restarting the target would not propagate to
them.

`scripts/advandeb-kb.service` is dead. It points at `knowledge-builder/dev-server`,
which was removed on 2026-03-21. Do not install it.

Restarting only the web half is cheap, because the KB package is an editable
install. The agent stack is a separate unit and is not touched:

```bash
sudo systemctl restart advandeb.service
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
| 8200  | nginx — production edge for advandeb.com (via Cloudflare Tunnel) | loopback | system nginx (host config, not in repo) |
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
| 27017 | MongoDB                          | `0.0.0.0` | container from the cadapti project's Docker Compose |
| 11434 | Ollama                           | loopback  | system / ollama serve      |

---

## Health checks

```bash
curl http://localhost:8400/api/health     # canonical — returns JSON incl. a Mongo ping
curl http://localhost:8080/health         # MCP gateway
```

`/api/health` is the endpoint to point monitors at. `/health` also exists and
returns the same payload. In production, though, nginx routes every non-`/api`
path to the static SPA, so `https://advandeb.com/health` returns HTML.

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
Locally, use `:8400` directly. In production, the only supported entry point is
advandeb.com, which goes through the tunnel to nginx on `:8200`. Port 80 on the
host is nginx's stock default site, not AdvanDEB.

**Chat says "The shared AI service is temporarily rate-limited"**
The default key's `DEFAULT_CHAT_RPM` budget is shared by everyone. Wait a
minute, or add your own key at `/settings/llm-keys`.

**Chat fails intermittently with 503 on the default model**
That is the upstream NVIDIA endpoint, not the app. Check the endpoint before
debugging the backend. Transient 5xx responses are retried (`6c3d95c`), but a
sustained outage is not.

**Saving an LLM key returns HTTP 500**
`LLM_KEY_ENCRYPTION_KEY` is unset. Generate one (see the `.env` table) and
restart the backend.

**New page or button appears but its API calls 404 (production)**
nginx serves the new `dist/` straight away, but the backend still runs the old
code. Restart `advandeb.service`.

**Graph view is empty but no errors**
Schemas are static (`BUILTIN_SCHEMAS`), so the dropdown is never empty. An
empty canvas usually means that schema's artifact has not been built yet, or
was built while ArangoDB was unreachable. Use the rebuild button in the KB
drawer for that schema.

**Graph view is stale after ingesting or chatting**
Expected. Graph artifacts are rebuilt by `GraphRebuildQueue` with a 5 s
settle delay and a **120 s floor** between rebuilds of the same schema. The
floor is deliberate — removing it drives back-to-back full-graph rebuilds that
pin a CPU and grow RSS. See `docs/STORAGE-CONTRACT.md` §4.

**`physiological_process` graph is empty or sparse**
Known. `regulates` and `depends_on` have no source data at all. `exhibited_by`
is derived through `sf_support` → facts → `knowledge_graph` → taxa, so it is
only as complete as those links. See `docs/knowledge_graph_scheme_descriptions.md`.

**`reproduction` graph never refreshes on its own**
Nothing calls `mark_dirty("reproduction")`. Rebuild it from the KB drawer, or
with `POST /api/kb/viz/schema/reproduction/rebuild`.

**Changes to Vue components not visible**
Run `npm run build` in `app/frontend/`. Both production nginx and the local
backend serve `app/frontend/dist/`. The dev server at `:5173` is separate.
