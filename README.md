# AdvanDEB

**A curated knowledge graph and AI research assistant for Dynamic Energy Budget (DEB) biology.**

AdvanDEB ingests scientific literature, extracts factual claims, links those
claims to a backbone of stylized facts and to an NCBI/GBIF taxonomy, and lets
researchers explore the result — as an interactive graph, or by asking questions
in natural language and getting answers with citations.

The design goal that shapes everything else: **answers must be traceable to
sources.** Hybrid retrieval, graph augmentation, and citation-carrying
responses all exist to serve that.

---

## Status

**Internal tool, under active development.** The retrieval, chat and
graph machinery is built and running against a substantial corpus at
advandeb.com.

Anonymous visitors see a public landing page, the login page, and the
elicitation enrolment form at `/elicitation/join`. **Everything that reads the
knowledge base requires an account.**

Known gaps are tracked in
[`docs/PLAN-2026-08-26.md`](docs/PLAN-2026-08-26.md). Its status table was
last updated 2026-10-28.

---

## What it does

| Area | Where | What |
|---|---|---|
| **Chat** | `/chat` | Questions answered from the corpus with numbered citations and a provenance trail. Users without their own key get a shared default model (NVIDIA Nemotron). Users can bring their own key for Anthropic, OpenAI, Gemini, GitHub Models or NVIDIA. |
| **Knowledge exploration** | `/documents`, `/facts` | The document corpus, extracted facts, stylized facts, and user fact suggestions. |
| **Knowledge Builder** | `/kb` (curators) | Graph views over seven schemas, ingestion, database inspection, document→taxon linking, review queues. |
| **Expert elicitation** | `/elicitation`, `/elicitation/join` | DEB experts score stylized facts against frozen evidence, to measure human agreement next to the machine panel's. See [`docs/ELICITATION.md`](docs/ELICITATION.md). |
| **tDEB simulator** | `/models`, `/models/:id` | Per-user transport-network DEB models, a backend ODE solver, and curator-published templates. |
| **Administration** | `/admin/users`, `/admin/experts` | User and role management, consented chat review with an audit log, expert enrolment and capability grants. |

---

## Corpus

Counts verified against ArangoDB on 2026-08-26; not re-counted since.

| | Count |
|---|---:|
| Curated, fully-processed papers | **1,253** |
| Stylized facts | 1,236 |
| Extracted facts | 109,395 |
| Fact → stylized-fact support edges | 31,311 |
| Document/fact → taxon/stylized-fact links (`knowledge_graph`) | 6,003 |
| Taxa (NCBI/GBIF) | 1,257,912 |
| Text chunks (embedded) | 3,077,659 |
| Broader literature index | 3,899,789 documents |

The distinction matters: **1,253 papers are curated and fully processed.** The
multi-million document and chunk counts are the surrounding literature index
that retrieval searches across.

The elicitation work uses the methods repository's stylized-fact collection
v1.0, which has 1,262 facts.

---

## Architecture

```
  advandeb.com ─▶ Cloudflare Tunnel ─▶ nginx 127.0.0.1:8200
                                         │ serves app/frontend/dist/ from disk
                                         │ proxies /api/ and /ws/
                                         ▼
  local dev ─────────────────────▶ App backend :8400  (FastAPI; also serves the SPA locally)
                                         │
     ┌───────────────────┬───────────────┼──────────────────────┐
     ▼                   ▼               ▼                      ▼
  External LLM APIs   retrieval_agent  chatbot_agent :8086    Datastores
  NVIDIA (default)    :8081            ReAct loop calling     ArangoDB :8529   canonical knowledge
  BYOK providers      (default and     agents :8081–8083      ChromaDB (disk)  vectors, ~17 GB
  (default and        BYOK paths)      (agent path)           MongoDB :27017   app state, users, chat
   BYOK paths)                                                Ollama :11434    local LLMs

  MCP gateway :8080 (Rust): only the REST fallback POST /api/chat/ uses it;
  its agent registry was empty on 2026-10-28.
```

**How a chat message actually flows.** The browser opens `/ws/chat/{session}`
on the backend, which takes one of three paths:

1. **Default.** The user has no key selected, and the operator has set
   `DEFAULT_CHAT_API_KEY`. The backend runs the KAG pipeline itself:
   - it calls the retrieval agent on `:8081` directly;
   - it expands the hits through the ArangoDB graph;
   - it builds an evidence registry of numbered citations;
   - it answers with NVIDIA's `nemotron-3-ultra` on one shared, rate-limited
     key.
2. **BYOK.** Same pipeline, with the user's own provider and key.
3. **Agent.** With no default key, or for a BYOK session in "react" mode, the
   backend hands the message to the chatbot agent on `:8086`. The agent runs a
   ReAct loop and calls the retrieval, graph-explorer and synthesis agents
   directly, on local Ollama models or the user's BYOK model.

The MCP gateway is not on any of these paths.

**Network exposure.** nginx, the gateway, the agents, ArangoDB and Ollama bind
to loopback. **The backend (`:8400`) and MongoDB (`:27017`) bind to all
interfaces.** MongoDB runs in a container defined by another project's Docker
Compose (cadapti), not by this repo.

**Retrieval** is hybrid:
- vector search over ChromaDB embeddings;
- keyword search over ArangoDB full-text indexes;
- the two combined with Reciprocal Rank Fusion;
- optional LLM reranking over the top candidates.

Full detail: [`docs/SYSTEM-OVERVIEW.md`](docs/SYSTEM-OVERVIEW.md).

---

## Repository layout

This is a monorepo.

| Path | What it is |
|---|---|
| `app/` | The AdvanDEB application — FastAPI backend (`app/backend/`) and Vue 3 frontend (`app/frontend/`). The single entry point for users. |
| `knowledge-builder/` | `advandeb_kb` — the Python library for ingestion, chunking, embedding, extraction, retrieval, graph building, LLM providers, and the six agents. Installed into the app with `pip install -e`. Not a service. |
| `mcp/` | The Rust MCP gateway. Routes tool calls to registered agents; not on the main chat path. |
| `docs/` | Architecture, storage semantics, graph schemas, elicitation, roadmap, and the change plan. |
| `scripts/` | Start/stop scripts, systemd units (`scripts/systemd/`), maintenance and migration scripts. |
| `monitoring/` | Prometheus and Grafana configuration. |
| `tests/` | Repo-level tests. Component tests live under `app/backend/tests/` and `knowledge-builder/tests/`. |
| `analysis/` | Analysis notebooks and supporting-evidence bundles. |
| `papers/`, `data/` | Source PDFs and the ChromaDB vector store. Large; not in version control. |

**Stack:** Python ≥3.11 · Vue 3.4 + Vite 5 · Rust 2021 · FastAPI · MongoDB ·
ArangoDB · ChromaDB · Ollama · SciPy (tDEB solver)

---

## Getting started

Full setup, prerequisites, environment variables, and troubleshooting are in
**[`RUNNING.md`](RUNNING.md)** — start there.

The short version:

```bash
conda activate advandeb
cd app/backend
pip install -r requirements.txt
pip install -e ../../knowledge-builder
cp .env.example .env        # then fill in JWT_SECRET_KEY, ARANGO_*, LLM_KEY_ENCRYPTION_KEY, DEFAULT_CHAT_API_KEY
uvicorn app.main:app --host 0.0.0.0 --port 8400 --reload
```

Then the agent stack, if you need chat (from the repo root):

```bash
./scripts/start_all.sh
```

The app is at **http://localhost:8400**, and the health check is at
`/api/health`. Locally the backend serves the built SPA; run `npm run build`
in `app/frontend/` first.

**You will need:**
- MongoDB, ArangoDB and Ollama running locally;
- roughly 20 GB of free disk for the vector store;
- an NVIDIA API key for the default chat model, or your own key added in the
  app.

`RUNNING.md` covers all of it — including the failure modes that look like
bugs but are missing configuration.

---

## Documentation

| Document | What it answers |
|---|---|
| [`RUNNING.md`](RUNNING.md) | How do I get this running, and why is it broken? |
| [`docs/SYSTEM-OVERVIEW.md`](docs/SYSTEM-OVERVIEW.md) | What are the components, how does chat work, what's built vs. planned? |
| [`docs/STORAGE-CONTRACT.md`](docs/STORAGE-CONTRACT.md) | Which store owns which entity, and how stale can copies be? |
| [`docs/knowledge_graph_scheme_descriptions.md`](docs/knowledge_graph_scheme_descriptions.md) | What are the nodes, edges, and graph schemas? |
| [`docs/ELICITATION.md`](docs/ELICITATION.md) | How does expert elicitation work — tiers, calibration, enrolment, DOI references? |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Where is the project, phase by phase? |
| [`docs/PLAN-2026-08-26.md`](docs/PLAN-2026-08-26.md) | What is open, what is done, and what's known-broken? |
| [`docs/README.md`](docs/README.md) | Index of everything in `docs/`, including the historical documents. |

Architecture diagrams (PlantUML, with rendered PNG/SVG) are in
`docs/diagrams/`. They predate the MongoDB→ArangoDB migration and have not been
re-verified.

---

## Development

**Tests.** These are the commands CI runs, made to work locally. Run each one
from the repo root; each block is self-contained.

Backend (48 tests). Run it via `python -m pytest`: plain `pytest` does not put
`app/backend` on `sys.path`, so every module that imports `app.*` fails to
collect.

```bash
cd app/backend && JWT_SECRET_KEY=local-test-secret-key-at-least-32-chars ENVIRONMENT=development MONGODB_URI=mongodb://127.0.0.1:1 python -m pytest -q
```

Repo-level tests (72 tests). `tests/integration/` is excluded because it
probes the live services.

```bash
python -m pytest -q tests --ignore=tests/integration
```

Library tests. Currently red, see below.

```bash
cd knowledge-builder && python -m pytest -q tests
```

Frontend (vitest). Currently red, see below.

```bash
cd app/frontend && npm test
```

Gateway. Currently does not compile, see below.

```bash
cd mcp && cargo test
```

The backend tests mock MongoDB. Pointing `MONGODB_URI` at an unreachable port
makes sure a stray real connection fails instead of reaching a live database.
**Never run tests from a checkout whose `app/backend/.env` points at
production.**

> **Known state, 2026-10-28: CI has failed on every push to `main` since at
> least 2026-06-04** — all three jobs:
>
> - **Backend:** CI runs plain `pytest`, which hits the import problem above.
> - **Frontend:** `vitest run` also collects the Playwright specs in
>   `tests/e2e/`, and they fail.
> - **Gateway:** `tokio::signal` is used without tokio's `signal` feature.
>
> Locally, besides those:
>
> - `knowledge-builder/tests` has 2 modules that fail to import
>   (`advandeb_kb.database.mongodb` is gone) and 8 failing tests.
> - The knowledge-builder CI step ends in `|| true`, which hides all of this.
> - Repo-root `tests/` is not run in CI at all.
>
> Tracked as C1 in the plan. Do not read a green build as proof of health
> until C1 is closed.

**Frontend builds** go to `app/frontend/dist/`.
- In production, nginx serves that directory directly, so a new build is live
  at once.
- Locally, the backend serves it on `:8400`.
- The Vite dev server on `:5173` (`npm run dev`) is separate and proxies to
  the backend.

---

## Licensing

**No licence has been granted.** AdvanDEB is an internal research tool of the
project below. The GitHub repository is publicly visible, but there is no
`LICENSE` file, so default copyright applies: the code may be read, but it is
not licensed for reuse, modification, or redistribution. All rights reserved.

This was decided on 2026-10-28: no licence until the work reaches a state
meant for outside use. If you want to use or build on AdvanDEB before then,
contact the maintainer first.

Dependency updates arrive automatically via Dependabot.

---

## Citation and funding

Citation metadata is in [`CITATION.cff`](CITATION.cff).

This work is funded by the **Croatian Science Foundation (Hrvatska zaklada za
znanost, HRZZ)** under project **IP-2024-05-3615-AdvanDEB**.
