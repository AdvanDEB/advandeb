# AdvanDEB

**A curated knowledge graph and AI research assistant for Dynamic Energy Budget (DEB) biology.**

AdvanDEB ingests scientific literature, extracts factual claims, links those
claims to a backbone of stylized facts and to an NCBI/GBIF taxonomy, and lets
researchers explore the result — as an interactive graph, or by asking questions
in natural language and getting answers with citations.

The design goal that shapes everything else: **answers must be traceable to
sources.** Hybrid retrieval, multi-agent verification, and citation-carrying
responses all exist to serve that.

---

## Status

**Internal beta, under active development.** The retrieval and multi-agent
machinery is built and running against a substantial corpus. The public-facing
surface is not finished: there is currently no landing page above the
authentication wall and no anonymous read access.

Current priorities and known gaps are tracked honestly in
[`docs/PLAN-2026-08-26.md`](docs/PLAN-2026-08-26.md).

---

## Corpus

| | Count |
|---|---:|
| Curated, fully-processed papers | **1,253** |
| Stylized facts | 1,236 |
| Extracted facts | 109,395 |
| Fact → stylized-fact support edges | 31,311 |
| Taxa (NCBI/GBIF) | 1,257,912 |
| Text chunks (embedded) | 3,077,659 |
| Broader literature index | 3,899,789 documents |

The distinction matters: **1,253 papers are curated and fully processed.** The
multi-million document and chunk counts are the surrounding literature index
that retrieval searches across.

---

## Architecture

```
                         ┌──────────────────────────┐
      browser  ─────────▶│  App backend  :8400      │
                         │  FastAPI + Vue SPA       │
                         │  (same origin, no nginx) │
                         └────────┬─────────────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    ▼                            ▼
         ┌────────────────────┐      ┌──────────────────────┐
         │ MCP Gateway  :8080 │      │  Datastores          │
         │ (Rust, loopback)   │      │                      │
         └─────────┬──────────┘      │  ArangoDB   :8529    │ canonical knowledge
                   │                 │  ChromaDB   (disk)   │ vectors, ~17 GB
                   ▼                 │  MongoDB    :27017   │ app state + materialized graph
     ┌───────────────────────────┐   └──────────────────────┘
     │ 6 agents  :8081–8086      │
     │ retrieval · graph_explorer│   ┌──────────────────────┐
     │ synthesis · query_planner │──▶│  Ollama     :11434   │ local LLM inference
     │ curator   · chatbot       │   └──────────────────────┘
     └───────────────────────────┘
```

Everything except the app backend binds to loopback.

**Retrieval** is hybrid: vector search over ChromaDB embeddings, keyword search
over ArangoDB full-text indexes, combined with Reciprocal Rank Fusion, with
optional LLM reranking over the top candidates.

Full detail: [`docs/SYSTEM-OVERVIEW.md`](docs/SYSTEM-OVERVIEW.md).

---

## Repository layout

This is a monorepo.

| Path | What it is |
|---|---|
| `app/` | The AdvanDEB application — FastAPI backend (`app/backend/`) and Vue 3 frontend (`app/frontend/`). The single entry point for users. |
| `knowledge-builder/` | `advandeb_kb` — the Python library providing ingestion, chunking, embedding, extraction, retrieval, graph building, and the six agents. Installed into the app with `pip install -e`. Not a service. |
| `mcp/` | The Rust MCP gateway. Routes tool calls between the backend and the agents. |
| `docs/` | Architecture, storage semantics, graph schemas, roadmap, and the current change plan. |
| `scripts/` | Start/stop scripts and systemd units. |
| `monitoring/` | Prometheus and Grafana configuration. |
| `tests/` | Repo-level tests. Component tests live under `app/backend/tests/` and `knowledge-builder/tests/`. |
| `analysis/` | Analysis notebooks and supporting-evidence bundles. |
| `papers/`, `data/` | Source PDFs and the ChromaDB vector store. Large; not in version control. |

**Stack:** Python ≥3.11 · Vue 3.4 + Vite 5 · Rust 2021 · FastAPI · MongoDB ·
ArangoDB · ChromaDB · Ollama

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
cp .env.example .env        # then fill in JWT_SECRET_KEY and the ARANGO_* vars
uvicorn app.main:app --host 0.0.0.0 --port 8400 --reload
```

Then the agent stack, if you need chat:

```bash
./scripts/start_all.sh
```

App at **http://localhost:8400**. Health check at `/api/health`.

You will need MongoDB, ArangoDB, and Ollama running locally, plus roughly 20 GB
of free disk for the vector store. `RUNNING.md` covers all of it — including the
failure modes that look like bugs but are missing configuration.

---

## Documentation

| Document | What it answers |
|---|---|
| [`RUNNING.md`](RUNNING.md) | How do I get this running, and why is it broken? |
| [`docs/SYSTEM-OVERVIEW.md`](docs/SYSTEM-OVERVIEW.md) | What are the components, and what's built vs. planned? |
| [`docs/STORAGE-CONTRACT.md`](docs/STORAGE-CONTRACT.md) | Which store owns which entity, and how stale can copies be? |
| [`docs/knowledge_graph_scheme_descriptions.md`](docs/knowledge_graph_scheme_descriptions.md) | What are the nodes, edges, and graph schemas? |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Where is the project, phase by phase? |
| [`docs/PLAN-2026-08-26.md`](docs/PLAN-2026-08-26.md) | What is being worked on now, and what's known-broken? |
| [`docs/REVIEW-2026-05-18.md`](docs/REVIEW-2026-05-18.md) | Historical review. Superseded — read the plan instead. |

Architecture diagrams (PlantUML, with rendered PNG/SVG) are in
`docs/diagrams/`. Note that the diagram set predates the ongoing
MongoDB→ArangoDB migration and has not been re-verified.

---

## Development

**Tests**

```bash
cd app/backend && pytest -q          # application backend
cd knowledge-builder && pytest -q    # library
cd mcp && cargo test                 # gateway
cd app/frontend && npm run test:unit # frontend
```

**CI** runs on every push and pull request via
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) — three jobs: backend
pytest, frontend `vue-tsc` + vitest, and `cargo test` + `cargo clippy --deny
warnings` for the gateway.

> **Known gap:** the knowledge-builder CI job currently swallows failures and
> does not cover the repo-root `tests/` directory. Tracked as C1 in the plan and
> being fixed. Do not read a green build as proof the library is healthy.

**Frontend builds** go to `app/frontend/dist/` and are served directly by the
backend — after `npm run build`, restart the backend to see changes at `:8400`.
The Vite dev server on `:5173` is separate and proxies to the backend.

---

## Licensing and contribution status

**This repository is public, but no license has been chosen yet.** There is no
`LICENSE` file, which means default copyright applies: the code is readable, but
it is not licensed for reuse, modification, or redistribution.

Until a license is added, please treat this repository as **source-available,
all rights reserved**. If you want to use or build on AdvanDEB, get in touch
first.

Selecting a license is a tracked decision (C16 in the plan). Some existing
documentation describes a fork-and-pull-request contribution workflow; that
workflow is not yet supported by the licensing, and those references are being
reconciled.

Dependency updates arrive automatically via Dependabot.

---

## Citation

There is no `CITATION.cff` yet. If you reference AdvanDEB in academic work,
please contact the maintainers for the current citation form.
