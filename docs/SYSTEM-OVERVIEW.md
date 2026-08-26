# AdvanDEB System Overview

> **Reconciled 2026-08-26** against the running system. The previous revision
> described a planned architecture, much of which was built differently or not
> at all. Sections below distinguish **what exists** from **what is planned**,
> and every claim about the running system was verified.
>
> Operational detail: `RUNNING.md`. Storage semantics:
> `docs/STORAGE-CONTRACT.md`. Graph schemas:
> `docs/knowledge_graph_scheme_descriptions.md`. Current work:
> `docs/PLAN-2026-08-26.md`.

---

## 1. What AdvanDEB is

A curated knowledge graph and AI research assistant for Dynamic Energy Budget
(DEB) biology. It ingests scientific literature, extracts factual claims, links
those claims to a backbone of stylized facts and to an NCBI/GBIF taxonomy, and
lets researchers explore the result — as a graph, or by asking questions in
natural language and getting cited answers.

The design goal that shapes everything else: **answers must be traceable to
sources.** Multi-agent verification, hybrid retrieval, and citation-carrying
responses all exist to serve that.

---

## 2. Components (as built)

### AdvanDEB app — `app/`
The single entry point. FastAPI backend serving `/api/*` **and** the compiled
Vue SPA from the same origin on `:8400`. No nginx, no separate frontend server.

Hosts authentication, chat, knowledge exploration, the admin console, and the
Knowledge Builder UI at `/kb`. Imports `advandeb-knowledge-builder` as an
editable Python package.

Frontend views: Home, Login, Chat, Documents, Facts, Scenarios, Models,
KnowledgeBuilder, Documentation, LLMKeys, PrivacySettings, AdminUsers,
AdminUserChats.

### advandeb-knowledge-builder — `knowledge-builder/`
A Python library, not a service. Provides ingestion, chunking, embedding, fact
extraction, taxonomy handling, graph building, hybrid retrieval, and the agent
implementations. Installed into the app's environment with `pip install -e`.

Also runnable standalone for batch processing.

### advandeb-MCP — `mcp/`
Rust MCP gateway on `:8080`, **loopback-only**. Routes tool calls between the
app backend and the six websocket agents; maintains the tool registry. Handles
SIGTERM for graceful shutdown. No authentication layer — it operates inside the
trusted boundary and is not externally reachable.

### The agents — `knowledge-builder/advandeb_kb/agents/`
Six Python websocket agents on `:8081–8086`, each with an HTTP health endpoint
at port + 100:

| Agent | Port | Role |
|---|---|---|
| `retrieval_agent` | 8081 | hybrid vector + keyword retrieval |
| `graph_explorer_agent` | 8082 | graph traversal and expansion |
| `synthesis_agent` | 8083 | composes cited answers |
| `query_planner_agent` | 8084 | decomposes queries into retrieval plans |
| `curator_agent` | 8085 | knowledge curation and validation |
| `chatbot_agent` | 8086 | conversation orchestration |

### Not built
**`advandeb-shared-utils`** was specified as a shared auth package. It does not
exist; auth lives in `app/backend/app/core/`. **`advandeb-modeling-assistant`**
as a distinct modeling component does not exist either — the name in older docs
refers to what is now simply "the app." Actual modeling assistance is Phase 2,
not started.

---

## 3. External services

| Service | Role | Bind |
|---|---|---|
| **ArangoDB** | canonical knowledge store (`advandeb_kb`) | loopback `:8529` |
| **ChromaDB** | canonical vector store, on-disk `data/chromadb` (~17 GB) | filesystem |
| **MongoDB** | application store (`advandeb`) + transitional KB store | `:27017` |
| **Ollama** | local LLM inference | loopback `:11434` |
| **Google OAuth 2.0** | optional sign-in — **currently hidden in the UI** | — |

**Redis is not used.** `CacheService` supports a Redis backend if a URL is
configured, but nothing configures one; the cache runs in-process.

---

## 4. Retrieval architecture

`HybridRetrievalService` is the core of the anti-hallucination design:

1. **Vector search** — cosine similarity over ChromaDB embeddings
2. **Keyword search** — ArangoDB full-text indexes (`documents.content`,
   `documents.abstract`, `facts.text`, `stylized_facts.description`,
   `chunks.text`), with a MongoDB fallback
3. **RRF fusion** — Reciprocal Rank Fusion combines the two ranked lists
4. **LLM reranking** — optional, via Ollama, over the top candidates

Sync Arango calls run through a 4-worker `ThreadPoolExecutor`. At the current
corpus size this is an unmeasured throughput ceiling — see C15 in the plan.

---

## 5. Corpus scale (verified 2026-08-26)

ArangoDB `advandeb_kb`:

| | Count |
|---|---:|
| documents (broad literature index) | 3,899,789 |
| chunks | 3,077,659 |
| taxa | 1,257,912 |
| facts | 109,395 |
| fact → stylized-fact support edges | 31,311 |
| citation edges | 8,521 |
| **curated ingested papers** (`document_meta`) | **1,253** |
| stylized facts | 1,236 |

The distinction matters when quoting numbers publicly: 1,253 papers are fully
curated and processed; the multi-million document and chunk counts are the
surrounding literature index.

---

## 6. Authentication & authorization (as built)

**Methods**
- Native email + password — bcrypt, with constant-time comparison against a
  dummy hash on user-not-found
- Google OAuth 2.0 — implemented, **currently hidden in the UI**
- GitHub OAuth device flow — for repository-linked features
- JWT — access tokens (1 h) and refresh tokens (30 d), each tagged with an
  explicit `type` claim that `verify_token` enforces

**Session lifecycle**
- `/logout` revokes the refresh token by `jti`, recorded in `revoked_tokens`
  with a TTL index
- `slowapi` rate-limits the auth endpoints

**Roles — what is actually implemented**

Three roles, checked in `app/backend/app/core/dependencies.py`:

| Role | Meaning |
|---|---|
| `administrator` | full access, user management, admin console |
| `knowledge_curator` | upload documents, contribute knowledge |
| `knowledge_explorator` | default role on account creation; read access |

Live distribution across 9 users: 1 administrator, 2 curators (who also hold
explorator), 6 explorator-only.

**Capabilities — specified, not implemented**

The user model carries a `capabilities: List[str]` field, and
`user_service.py` initialises it to `[]` on every user. **No code grants,
requests, or checks a capability.** The previously documented capability set —
Knowledge Creation, Agent Access, Analytics Access, Reviewer Status — is a
design that was never wired up. Treat it as planned, not available.

**Platform API keys — not implemented**

Older docs described API keys for programmatic platform access. What exists is
`user_llm_keys` — BYOK credentials users supply for *their own* LLM providers
(Anthropic, Nvidia, and others). That is a different feature and does not
authenticate anyone to AdvanDEB.

**No anonymous access.** Every route requires authentication. The
`Knowledge Explorator` role described elsewhere as "read-only public browsing"
still requires an account. Whether to open a public read path is the open
strategic question — C6 in the plan.

---

## 7. Data model

Knowledge entities live in ArangoDB; see
`docs/knowledge_graph_scheme_descriptions.md` for the full node/edge reference
and the important distinction between the **canonical** Arango layer and the
**materialized** MongoDB layer the frontend renders.

Application entities in MongoDB `advandeb`: `users`, `chat_sessions`,
`chat_messages`, `chat_access_log`, `chat_message_feedback`, `user_llm_keys`,
`revoked_tokens`, `agent_sessions`, `agent_memory`, `ingestion_jobs`,
`ingestion_batches`, and the submission collections.

A PlantUML class diagram is at `docs/diagrams/knowledge-builder-data-model.puml`
(rendered `.png` / `.svg` alongside). Note that the diagram set predates the
Mongo→Arango migration and has not been re-verified.

**Provenance is not persisted.** `provenance_traces` is empty and nothing writes
to it; provenance chains are reconstructed on read. See
`docs/STORAGE-CONTRACT.md` §5 — this is a substantive gap given §1's stated goal.

---

## 8. Review workflow

Facts and stylized facts carry `status` fields, and submission collections
(`document_submissions`, `fact_submissions`, `sf_submissions`) exist — all
currently empty. The reviewer role, approval transitions, and notification paths
described in earlier revisions are **not implemented**. Content review today is
manual and direct.

---

## 9. Dangling references

These documents are cited by older revisions and **do not exist** anywhere in
the repository. Citations to them have been removed from the reconciled docs;
if the content still matters, it needs to be rewritten rather than linked:

- `USER-MANAGEMENT-PLAN.md`
- `SHARED-UTILS-PLAN.md`
- `APP-VISUALIZATION-PLAN.md`
- `MCP-MULTI-AGENT-COORDINATION-PLAN.md`
