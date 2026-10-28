# AdvanDEB System Overview

> **Reconciled 2026-08-26** against the running system, and **updated
> 2026-10-28** for the work that landed after it: the tDEB simulator and model
> library, expert elicitation, the capability gate, and the chat paths. The
> previous revision described a planned architecture, much of which was built
> differently or not at all. Sections below distinguish **what exists** from
> **what is planned**.
>
> Operational detail: `RUNNING.md`. Storage semantics:
> `docs/STORAGE-CONTRACT.md`. Graph schemas:
> `docs/knowledge_graph_scheme_descriptions.md`. Expert elicitation:
> `docs/ELICITATION.md`. Current work: `docs/PLAN-2026-08-26.md`.

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
The single entry point for users. A FastAPI backend serves `/api/*` and `/ws/*`
on `:8400`. The same process can also serve the compiled Vue SPA from
`app/frontend/dist/`; locally, everything is same-origin on `:8400`.

**Production edge.** advandeb.com is reached through a Cloudflare Tunnel to
nginx on `127.0.0.1:8200`. nginx serves the SPA straight from
`app/frontend/dist/` on disk, and proxies `/api/` and `/ws/` to `:8400`.

A consequence worth knowing: a new `npm run build` is live in production at
once, but backend changes are live only after the backend restarts. The two
can drift apart.

The backend hosts:
- authentication and chat;
- knowledge exploration (Documents, Facts, Knowledge Builder at `/kb`);
- the tDEB simulator and model library;
- expert elicitation;
- the admin console.

It imports `advandeb_kb` as an editable Python package.

**Frontend routes** (`app/frontend/src/router/index.ts`):

| Path | View | Access |
|---|---|---|
| `/` | Home — dashboard when signed in, public landing page otherwise | public |
| `/login` | Login | public |
| `/elicitation/join` | Enrolment — public sign-up for elicitation | **public** |
| `/chat`, `/documents`, `/facts`, `/documentation` | Chat, Documents, Facts, Documentation | signed in |
| `/elicitation` | Elicitation queue | signed in; API needs `sf_elicitation` |
| `/models` | ModelsLibrary — the user's tDEB models and published templates | signed in |
| `/models/:id` | Models — the tDEB model editor and simulator | signed in |
| `/settings/llm-keys`, `/settings/privacy` | LLMKeys, PrivacySettings | signed in |
| `/kb` | KnowledgeBuilder | curator or administrator |
| `/admin/users`, `/admin/users/:id/chats` | AdminUsers, AdminUserChats | administrator |
| `/admin/experts` | AdminExperts — enrolment review, capability grants, panel progress | administrator |

The Scenarios page was removed in `d4a38f3` (2026-09-21) and replaced by
Elicitation.

A user whose only role is `external_contributor` is confined to
`/elicitation`, `/settings` and `/login`.

### tDEB simulator and model library — `app/backend/app/tdeb/`
A transport-network DEB simulator, ported from the private
`sciom/advanDEB_tDEB_simulator` (`add5ecc`, 2026-08-29). The library and
templates came later (`5b53dcf`, 2026-09-09).

**Models are per-user.**
- Each model is a network of nodes and edges, stored in Mongo `tdeb_models`
  and owned via `owner_id`. Limits: 200 nodes and 400 edges.
- Equations are per-user overrides in `tdeb_equations`, merged over
  `app/backend/app/tdeb/core/default_equations.json`.

**Editing is saved as it happens.** Every edit is persisted through the
node/edge endpoints, and the editor shows a saving/saved indicator.

**Curators can publish a model as a template.** Any user can duplicate a
published template. Built-in starting templates also come from code
(`GET /api/tdeb/templates`).

**Simulation runs on the backend.** The solver is
`scipy.integrate.solve_ivp`, stiff by default, run in a thread pool. Two
entry points: `POST /api/tdeb/models/{id}/simulate`, or streamed over
`WS /api/tdeb/ws/simulate/{model_id}`.

This is the first piece of actual modeling capability (Phase 2).

### Expert elicitation — `/elicitation`
DEB experts score stylized facts against frozen evidence, so that human
agreement can be measured next to the machine panel's. In brief:
- two tiers, `panel` and `contributor`, never pooled;
- a calibration gate enforced on the server;
- public enrolment at `/elicitation/join`, reviewed by an admin at
  `/admin/experts`;
- the tier stamped on every record;
- an evidence-scoring task that leads the queue;
- expert-asserted DOI references that double as a retrieval-recall
  measurement.

The full description is in `docs/ELICITATION.md`.

### advandeb-knowledge-builder — `knowledge-builder/`
A Python library, not a service. Provides ingestion, chunking, embedding, fact
extraction, taxonomy handling, graph building, hybrid retrieval, and the agent
implementations. Installed into the app's environment with `pip install -e`.

Also runnable standalone for batch processing.

### advandeb-MCP — `mcp/`
Rust MCP gateway on `:8080`, **loopback-only**. It routes tool calls to
registered agents and keeps a tool registry. It has no authentication layer:
it runs inside the trusted boundary and is not externally reachable.

The source handles SIGTERM for graceful shutdown. **At HEAD the crate does
not compile**, though: tokio's `signal` feature is missing (C1). The deployed
binary was built on 2026-03-13, before both the SIGTERM handler and the
loopback-by-default change.

**The gateway is not on the main chat path.** The backend talks to the
chatbot agent (`:8086`) and the retrieval agent (`:8081`) directly; see §4a.
The gateway is used only by the REST `POST /api/chat/` fallback, which the
frontend does not call.

`scripts/start_all.sh` and `scripts/start_stack.sh` register the six agents
via `scripts/register_all_agents.sh`. The registry is in memory, though, and
on 2026-10-28 the running gateway reported `{"agents":[]}`. A gateway restart
without re-registration empties it.

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

Each agent's local LLM is Ollama. The defaults are in
`advandeb_kb/config/settings.py`:
- `OLLAMA_MODEL` / `CHAT_ANSWER_MODEL` = `deepseek-r1:latest`;
- `CHAT_GRAPH_MODEL` / `CHAT_FOLLOWUP_MODEL` = `gemma3:latest`.

The chatbot agent can also drive a user's BYOK model through its ReAct loop.

### Not built
**`advandeb-shared-utils`** was specified as a shared auth package. It does
not exist; auth lives in `app/backend/app/core/`.

**`advandeb-modeling-assistant`** as a separate component does not exist
either. Older docs use the name for what is now simply "the app".

What exists of modeling assistance is the tDEB simulator above. The assistant
proper — LLM-guided model construction from the knowledge base — is not built.

---

## 3. External services

| Service | Role | Bind / location |
|---|---|---|
| **ArangoDB** | canonical knowledge store (`advandeb_kb`) | loopback `:8529` |
| **ChromaDB** | canonical vector store, on-disk `data/chromadb` (~17 GB) | filesystem |
| **MongoDB** | application store (`advandeb`) + transitional KB store | `:27017` on **all interfaces** — a container defined in another project's (cadapti) Docker Compose, not managed from this repo |
| **Ollama** | local LLM inference: agents, extraction, reranking, follow-up suggestions | loopback `:11434` |
| **NVIDIA API** (`integrate.api.nvidia.com`) | the **default chat model** for users without their own key — see §4a | external |
| **BYOK providers** — Anthropic, OpenAI, Google Gemini, GitHub Models, NVIDIA | chat with the user's own key | external |
| **OpenAlex, Crossref** | DOI resolution for expert references; OpenAlex metadata backfill | external |
| **GitHub OAuth** (device flow) | connecting GitHub Models without pasting a key | external |
| **Google OAuth 2.0** | optional sign-in — **currently hidden in the UI** | external |
| **Cloudflare Tunnel → nginx `127.0.0.1:8200`** | production edge for advandeb.com | host config, not in this repo |

**Redis is not used.** `CacheService` supports a Redis backend if a URL is
configured, but nothing configures one; the cache runs in-process. Celery was
replaced by FastAPI background tasks on 2026-03-16 (`8e3de1f`). It is still
listed in `knowledge-builder/pyproject.toml`, but nothing imports it.

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

## 4a. Chat paths and LLM providers (as built)

The browser opens `WS /ws/chat/{session_id}`. `ChatService.process_message_stream`
then picks one of three paths:

| Situation | Path | LLM |
|---|---|---|
| No BYOK key selected, and `DEFAULT_CHAT_API_KEY` is set | **Default.** In-backend `ByokChatService`, KAG pipeline | `DEFAULT_CHAT_MODEL` via `DEFAULT_CHAT_PROVIDER` — by default `nvidia/nemotron-3-ultra-550b-a55b` on NVIDIA's API, on **one shared key**, rate-limited to `DEFAULT_CHAT_RPM` (40) turns/min across all users |
| A BYOK key selected, "final" mode | **BYOK.** In-backend `ByokChatService`, KAG pipeline | the user's provider and model |
| No default key, or a BYOK session in "react" mode | **Agent.** Backend → `chatbot_agent` `:8086` over a websocket; the agent runs a ReAct loop calling retrieval `:8081`, graph explorer `:8082` and synthesis `:8083` directly | Ollama (`deepseek-r1`), or the user's BYOK model |

In the two in-backend paths, retrieval goes straight to the retrieval agent
at `RETRIEVAL_AGENT_WS` (`ws://localhost:8081`), bypassing the gateway.
Follow-up question suggestions use Ollama (`CHAT_FOLLOWUP_MODEL`) on every
path, best-effort.

All chat paths require `MCP_SERVER_ENABLED=true`, despite the name. With it
off, chat answers "MCP server is not enabled."

### KAG

In this codebase **KAG** (knowledge-augmented generation) is the in-backend
answer pipeline in `app/backend/app/services/byok_chat_service.py`:

1. **Retrieve.** Three searches run in parallel: hybrid chunk retrieval,
   direct stylized-fact matches, and AdvanDEB's own platform docs.
2. **Graph-augment.** The retrieved chunks are expanded two hops through the
   ArangoDB knowledge graph (`GraphExpansionService.expand_from_chunks`). This
   pulls in linked facts, stylized facts and taxa.
3. **Build an EvidenceRegistry** from everything retrieved (below).
4. **Synthesize.** A provider with native tool calling runs an **agentic
   loop**: it can call search, graph, `get_claim_consensus` and
   `search_platform_docs` tools for more evidence before answering. These are
   Anthropic, OpenAI, GitHub Models and NVIDIA, including the default path.
   Gemini, and Ollama used as BYOK, get **single-pass KAG**: the whole
   registry goes into one prompt.

KAG differs from plain RAG in step 2: the model sees curated graph structure,
not just text passages.

### EvidenceRegistry

`EvidenceRegistry` (`advandeb_kb/services/evidence_registry_service.py`)
freezes the retrieved evidence into a citation registry **before** the answer
is generated. Each item gets a stable marker:

| Marker | Evidence |
|---|---|
| `[1]`, `[2]`, … | text chunks from the corpus |
| `[G1]`, … | graph facts, including claim-consensus results |
| `[SF1]`, … | stylized facts |
| `[D1]`, … | sections of AdvanDEB's own documentation (`app/backend/app/data/platform_docs.json`) |

Entries are deduplicated by citation id. Evidence fetched mid-answer by the
agentic loop gets the next free marker, so earlier markers never change.
`extract_citations` maps the markers in the answer back to registry entries,
which become the citation badges and the provenance trail in the UI.

### BYOK providers

Users store their own keys at `/settings/llm-keys`. The supported providers
are in `advandeb_kb/services/llm_providers/registry.py`: `anthropic`,
`openai`, `gemini`, `github_models`, `nvidia`, and `ollama`.

**Keys are encrypted at rest** with Fernet, keyed by `LLM_KEY_ENCRYPTION_KEY`.
If that variable is unset, the app starts, but saving a key fails with HTTP
500.

**GitHub Models can be connected without pasting a key**, through GitHub's
OAuth device flow: `POST /api/users/me/llm-keys/oauth/github/start` and
`/poll`. `GITHUB_OAUTH_CLIENT_ID` must be set.

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
- GitHub OAuth device flow — **not a sign-in method**. It connects a user's
  GitHub Models access as a BYOK provider (§4a).
- JWT — access tokens (1 h) and refresh tokens (30 d), each tagged with an
  explicit `type` claim that `verify_token` enforces

**Session lifecycle**
- `/logout` revokes the refresh token by `jti`, recorded in `revoked_tokens`
  with a TTL index
- `slowapi` rate-limits the auth endpoints

**Roles — what is actually implemented**

Defined in `app/backend/app/core/dependencies.py` and
`app/backend/app/services/user_service.py`:

| Role | Meaning |
|---|---|
| `administrator` | full access, user management, admin console, expert management |
| `knowledge_curator` | upload documents, review, use the Knowledge Builder, publish tDEB templates |
| `knowledge_explorator` | default role on account creation; chat, read access, own tDEB models |
| `external_contributor` | minimum-privilege role for outside elicitation participants: elicitation and settings only, with no documents, chat, KB, graph or models |

Routes enforce roles with `require_admin` and `require_curator`.

**`external_contributor` is restricted only in the frontend router.** No
backend dependency excludes it. Its token can call every route that needs
only authentication: chat, documents, facts, provenance, chunk context. See
C25 in the plan.

**Capabilities — implemented, one so far**

The user model's `capabilities: List[str]` is now checked.
`require_capability(<name>)` admits administrators and any user holding the
capability. The only capability in use is `sf_elicitation`, which gates every
elicitation endpoint. For this capability, the `knowledge_curator` and
`external_contributor` roles also pass.

New users start with `capabilities: []`. The capability is granted:
- by an administrator, with `POST /api/elicitation/experts/{user_id}?granted=true`;
- automatically, when an enrolment request is approved.

The older capability set — Knowledge Creation, Agent Access, Analytics Access,
Reviewer Status — remains an unimplemented design.

**Platform API keys — not implemented**

Older docs described API keys for programmatic platform access. What exists is
`user_llm_keys` — BYOK credentials users supply for *their own* LLM providers
(Anthropic, Nvidia, and others). That is a different feature and does not
authenticate anyone to AdvanDEB.

**Anonymous access is limited to three things:**
- the landing page at `/` (`HomeView` has an unauthenticated branch since
  `0f1c24d`, 2026-05-21);
- the login page;
- the elicitation enrolment form, `POST /api/enrolment/request`, rate-limited
  to 5/min.

Every knowledge route requires an account. That includes the
`knowledge_explorator` role, which older docs described as "read-only public
browsing". Whether to open a public read path is the open strategic question
— C6 in the plan.

---

## 7. Data model

Knowledge entities live in ArangoDB; see
`docs/knowledge_graph_scheme_descriptions.md` for the full node/edge reference
and the important distinction between the **canonical** Arango layer and the
**graph artifacts** the frontend renders. The artifacts are files built from
Arango; they are not the legacy Mongo `graph_nodes` / `graph_edges`, which
nothing reads any more.

Application entities in MongoDB `advandeb`:
- **users and auth:** `users`, `revoked_tokens`, `user_llm_keys`;
- **chat:** `chat_sessions`, `chat_messages`, `chat_access_log`,
  `chat_message_feedback`;
- **agents:** `agent_sessions`, `agent_memory`;
- **ingestion:** `ingestion_jobs`, `ingestion_batches`, and the submission
  collections;
- **tDEB:** `tdeb_models`, `tdeb_equations`;
- **elicitation:** `elicitation_queue`, `elicitations`, `evidence_sets`,
  `elicitation_calibration`, `elicitation_calibration_results`,
  `enrolment_requests`, `expert_references` (see `docs/ELICITATION.md` §7).

A PlantUML class diagram is at `docs/diagrams/knowledge-builder-data-model.puml`
(rendered `.png` / `.svg` alongside). Note that the diagram set predates the
Mongo→Arango migration and has not been re-verified.

**Provenance is not persisted.** `provenance_traces` is empty and nothing writes
to it; provenance chains are reconstructed on read. See
`docs/STORAGE-CONTRACT.md` §5 — this is a substantive gap given §1's stated goal.

---

## 8. Review workflow

Facts and stylized facts carry `status` fields. The submission collections
(`document_submissions`, `fact_submissions`, `sf_submissions`) exist and were
empty at the last count.

Since `8c5ee08` (2026-08-29), curators also see **review-queue counts** over
machine-generated output in ArangoDB (`GET /api/kb/db/review-queues`):
- pending facts;
- `sf_support` edges in status `suggested`;
- `studies` links in status `suggested`.

The KG Builder tab confirms or rejects document→taxon links.

The reviewer role, approval state machine and notification paths described in
earlier revisions are still **not implemented**. Expert elicitation (§2) is a
separate, purpose-built judgment workflow. It does not change the status of
facts.

---

## 9. Dangling references

These documents are cited by older revisions and **do not exist** anywhere in
the repository. Citations to them have been removed from the reconciled docs;
if the content still matters, it needs to be rewritten rather than linked:

- `USER-MANAGEMENT-PLAN.md`
- `SHARED-UTILS-PLAN.md`
- `APP-VISUALIZATION-PLAN.md`
- `MCP-MULTI-AGENT-COORDINATION-PLAN.md`
