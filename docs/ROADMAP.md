# AdvanDEB Cross-Repository Roadmap

> **Revised 2026-08-26.** This replaces the 2026-05-18 revision. The phase
> structure below is unchanged in spirit but re-anchored to what is actually
> running: every status claim here was verified against the live services,
> the three datastores, and the committed tree at `cb7dd3c1`. The change plan
> that used to live in `docs/REVIEW-2026-05-18.md` §11 is superseded by
> `docs/PLAN-2026-08-26.md`.

---

## 1. Where the system actually is (2026-08-26)

AdvanDEB is past the "does it work" stage and into the "can anyone else use
it" stage. The retrieval and multi-agent machinery is built, running, and
holding a substantial corpus. What is missing is almost entirely at the
edges: a public face, operational confidence, and documentation that matches
reality.

### Running topology (verified)

| Component | Port | Bind | Managed by |
|---|---|---|---|
| App backend — FastAPI + compiled Vue SPA | 8400 | `0.0.0.0` | `advandeb.service` |
| MCP gateway (Rust) | 8080 | `127.0.0.1` | `advandeb-stack.service` |
| Agents — retrieval, graph_explorer, synthesis, query_planner, curator, chatbot | 8081–8086 | `127.0.0.1` | `advandeb-stack.service` |
| MongoDB | 27017 | `0.0.0.0` | system |
| ArangoDB | 8529 | `127.0.0.1` | system |
| Ollama | 11434 | `127.0.0.1` | system |

All three units (`advandeb.target` → `advandeb.service` +
`advandeb-stack.service`) are active.

### Data on disk (verified counts, not estimates)

**ArangoDB `advandeb_kb`** — the canonical knowledge store:

| Collection | Count | Note |
|---|---|---|
| `documents` | 3,899,789 | broad literature index; 3,818,403 distinct titles |
| `chunks` | 3,077,659 | spanning 603,739 distinct documents |
| `chunk_belongs_to` | 2,464,969 | edge |
| `taxa` / `taxonomical` | 1,257,912 each | full taxonomy backbone |
| `facts` | 109,395 | across 11,913 distinct documents |
| `sf_support` | 31,311 | edge — stylized-fact support graph |
| `citations` | 8,521 | edge |
| `document_meta` | 1,253 | the curated, fully-ingested paper set |
| `stylized_facts` | 1,236 | |
| `knowledge_graph` | 35 | edge |
| `provenance_traces` | **0** | dead schema — provenance is reconstructed on read, never persisted. See `STORAGE-CONTRACT.md` §5. |

**ChromaDB** — 17 GB at `data/chromadb`.

**MongoDB** — two databases with deliberate but undocumented overlap:

- `advandeb` (app/user surface): 9 users, 1,695 documents, 28,309 facts,
  1,236 stylized facts, 49,700 graph nodes / 70,724 edges, 1,258,523
  taxonomy nodes, 1,316 ingestion jobs, 9 chat sessions / 37 messages.
- `advandeb_knowledge_builder_kb` (KB working surface): 1,305 documents,
  263,691 chunks, 63,709 facts, 102,060 graph nodes / 155,397 edges,
  1,257,912 taxonomy nodes, 7,529 snapshot cluster views.

**These are not three views of one dataset — they are three generations of the
same corpus, mid-migration.** `app/backend/app/core/config.py:61` states it
outright: `KB_DB_NAME` is *"Transitional: used during MongoDB→ArangoDB
migration. Remove after migration."* The second Mongo database is the previous
generation, still present and still written to by ingestion, visualization
artifacts, and user submissions.

Ownership, sync paths, and staleness tolerances are now written down in
`docs/STORAGE-CONTRACT.md`. **Finishing or formally abandoning that migration
is the largest untracked piece of work in the system.**

### Corpus scale correction

The previous revision described the corpus as "~1300 papers" with an
"sf_support graph at 3373 nodes / 2243 edges." Both numbers are now badly
stale: `document_meta` is 1,253 (so the curated set is roughly right), but
the surrounding literature index is three orders of magnitude larger, and
`sf_support` is at 31,311 edges. Any planning that assumed the small numbers
should be re-checked.

---

## 2. Phase status, reconciled

### Phase 0 — Multi-Agent RAG-KG Foundation — **SHIPPED**

Five specialized agents (`retrieval_agent`, `graph_explorer_agent`,
`synthesis_agent`, `query_planner_agent`, `curator_agent`) plus the
`chatbot_agent` orchestrator run under `advandeb-stack.service`. The Rust MCP
gateway routes between them. ArangoDB is the canonical KB store; ChromaDB
powers vector retrieval; `HybridRetrievalService` fuses vector + full-text
with RRF and optional LLM reranking.

All four slices (Semantic RAG, Multi-Agent Coordination, Graph-Augmented
Retrieval, Production Readiness) are shipped. Slice 4 was the last to close:
CI, rate limiting, graceful shutdown, loopback binding, and token revocation
all landed since May.

### Phase 0.5 — User Management & Authentication — **SHIPPED (with gaps)**

Shipped since the last revision: the administrator dashboard
(`AdminUsersView`, `AdminUserChatsView`), a staff-access audit log
(`chat_access_log`), a user-facing privacy opt-out (`PrivacySettingsView`),
real `/logout` with `jti` revocation, `slowapi` rate limiting on auth,
constant-time login, and the full JWT hardening set.

Still open: API-key management with capability scopes, the capability-request
workflow for existing curators, and email notifications. Google sign-in is
currently hidden in the UI (`ed3d21d6`) — that is a deliberate temporary
state and needs a decision, not just a re-enable.

### Phase 1 — Stabilize knowledge-builder — **SHIPPED (with gaps)**

CI exists (`.github/workflows/ci.yml`: backend pytest, frontend
vue-tsc + vitest, mcp cargo test + clippy). The backend suite is 15/15 green.
Two gaps, both tracked in the new plan: the KB job is `|| true` and points at
the wrong directory, and one root-level test module does not import.

### Phase 1.5 — App Visualization & UX — **SHIPPED**

Cosmograph WebGL canvas, live agent-activity panel, provenance trail panel,
and the enhanced chat interface with source cards are all in. Citation and
retraction signals on `claim_consensus` landed in the August merge.

### Phase 1.75 — MCP Gateway — **SHIPPED**

WebSocket MCP protocol, agent routing, tool registry, SIGTERM graceful
shutdown, loopback-only bind.

### Phase 2 — Modeling Assistant — **NOT STARTED**

Unchanged. `ScenariosView` and `ModelsView` exist in the frontend and
`scenario_service` / `model_service` in the backend, but these are the
knowledge-side scaffolding, not the modeling assistant itself.

### Phases 3 & 4 — **NOT STARTED**

Unchanged.

---

## 3. Shipped work that was never on the roadmap

The following are live in the product and had no roadmap entry. They are
recorded here so the roadmap stops under-describing the system:

- **BYOK (bring-your-own-key) chat** — `byok_chat_service`, `LLMKeysView`,
  `user_llm_keys`, per-provider adapters including Anthropic and Nvidia.
- **Admin console** — user management plus consented chat review, backed by
  an access audit log.
- **Graph analytics service** and the `claim_consensus` / `find_by_taxon`
  graph tools with citation + retraction signals.
- **AdvanDEB's own documentation as a citable `[D1]` evidence source**, with
  stable citation markers for evidence gathered mid-conversation.
- **Corpus quality gating** — domain-relevance gate and bibliographic noise
  filter at extraction, applied retroactively to the reproduction abstracts.
- **GitHub OAuth device flow** (`github_oauth_service`).
- **Prompt library** and an in-app `DocumentationView`.
- **Graph artifact / snapshot pipeline** — `graph_artifact_builder`,
  `graph_artifact_store`, `graph_snapshot_service`, `graph_rebuild_queue`.

---

## 4. Current quarter — Q3 2026

The theme is **"make it presentable and make it trustworthy."** The engine
works; nobody outside the project can see it, and we cannot yet prove it
stays working.

1. **Close the CI blind spot.** A test suite that silently passes is worse
   than no test suite.
2. **Give AdvanDEB a public face.** A landing page above the auth wall, and
   a decision on anonymous read-only knowledge browsing.
3. **Finish or formally abandon the Mongo→Arango migration.** The storage
   contract is now written (`docs/STORAGE-CONTRACT.md`); the half-migrated
   state it documents is the thing to resolve.
4. **Decide whether provenance becomes durable.** It is currently
   reconstructed on read, which means historical answers cannot be audited.
5. **Re-measure before re-claiming.** The performance targets below have
   still never been measured against the current build.

Detail, ordering, and acceptance criteria: `docs/PLAN-2026-08-26.md`.

---

## 5. Performance targets

Still targets, still unmeasured. Carried forward unchanged from the previous
revision so the gap stays visible:

- Frontend initial load: <3s
- Bundle size: <1MB gzipped
- Build time: <10s
- Lighthouse score: >90
- Backend health check: <100ms

`/api/health` now exists as the canonical endpoint, so the last one is
finally measurable.
