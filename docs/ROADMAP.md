# AdvanDEB Roadmap

> **Updated 2026-10-28.** Changes in this update:
> - phase statuses reconciled with the work that landed through `5ceb4fa`;
>   Phase 2 is now **in progress**;
> - expert elicitation added to the shipped list;
> - a Q4 2026 section added.
>
> No new goals were set: the goals discussion has not concluded. Everything
> else below is the 2026-08-26 revision.
>
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
| nginx — production edge (Cloudflare Tunnel → nginx → backend; serves `dist/` from disk) | 8200 | `127.0.0.1` | system (added 2026-10-28) |
| App backend — FastAPI + compiled Vue SPA | 8400 | `0.0.0.0` | `advandeb.service` |
| MCP gateway (Rust) | 8080 | `127.0.0.1` | `advandeb-stack.service` |
| Agents — retrieval, graph_explorer, synthesis, query_planner, curator, chatbot | 8081–8086 | `127.0.0.1` | `advandeb-stack.service` |
| MongoDB | 27017 | `0.0.0.0` | container from the cadapti project's Docker Compose |
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
| `knowledge_graph` | 6,003 | edge — 35 until the 2026-08-26 backfill (see `knowledge_graph_scheme_descriptions.md`) |
| `provenance_traces` | **0** | dead schema — provenance is reconstructed on read, never persisted. See `STORAGE-CONTRACT.md` §5. |

**ChromaDB** — 17 GB at `data/chromadb`.

**MongoDB** — two databases with deliberate but undocumented overlap:

- `advandeb` (app/user surface): 9 users, 1,695 documents, 28,309 facts,
  1,236 stylized facts, 49,700 graph nodes / 70,724 edges, 1,258,523
  taxonomy nodes, 1,316 ingestion jobs, 9 chat sessions / 37 messages.
  *(2026-10-28: the graph node and edge collections turned out to be legacy
  data that no code reads. `documents` was lost in September and rebuilt from
  Arango; see `STORAGE-CONTRACT.md` §2a.)*
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
`chatbot_agent` orchestrator, six in all, run under `advandeb-stack.service`.

*2026-10-28:* the agents call each other directly, and the backend calls the
retrieval and chatbot agents directly. The Rust MCP gateway is not on the main
chat path (`SYSTEM-OVERVIEW.md` §4a). Since August most chat turns run in the
backend's own KAG pipeline on an external model, not in the agent ReAct loop. ArangoDB is the canonical KB store; ChromaDB
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
vue-tsc + vitest, mcp cargo test + clippy).

*2026-10-28 correction:* **CI has failed on every push to `main` since at
least 2026-06-04, in all three jobs.** Run locally with
`python -m pytest`, the backend suite passes (48 tests) and the repo-root
suite passes (72). The knowledge-builder suite is red: 2 modules do not import
and 8 tests fail. The gateway does not compile. Details and causes are under
C1 in `PLAN-2026-08-26.md`. The root-level import failure noted in August (C2)
is fixed.

### Phase 1.5 — App Visualization & UX — **SHIPPED**

Cosmograph WebGL canvas, live agent-activity panel, provenance trail panel,
and the enhanced chat interface with source cards are all in. Citation and
retraction signals on `claim_consensus` landed in the August merge.

### Phase 1.75 — MCP Gateway — **SHIPPED**

WebSocket MCP protocol, agent routing, tool registry, SIGTERM graceful
shutdown, loopback-only bind.

*2026-10-28:* at HEAD the gateway does not compile. The SIGTERM handler uses
`tokio::signal`, but `mcp/Cargo.toml` lacks tokio's `signal` feature (C1).
The running binary was built on 2026-03-13. It predates both the SIGTERM
handler and the loopback-by-default change (`5b8361d`, 2026-05-21), so
neither is deployed, although production does listen on loopback only. The
registry is in memory and was empty in production on 2026-10-28; that is
harmless, because chat does not use the gateway.

### Phase 2 — Modeling Assistant — **IN PROGRESS** *(was "not started" on 2026-08-26)*

**Shipped:**
- the **tDEB transport-network simulator** (`add5ecc`, 2026-08-29), ported
  from the private `sciom/advanDEB_tDEB_simulator` and made per-user. It has a
  backend SciPy solver (stiff by default), editable equations, and a node/edge
  model editor at `/models/:id`.
- the **model library** at `/models`, with visible autosave and
  curator-published templates (`5b53dcf`, 2026-09-09).

**Not built:** the *assistant* part — using the knowledge base and chat to
propose, parameterise or critique a model.

The Scenarios page was removed on 2026-09-21 (`d4a38f3`). The legacy
`/api/models` route and `model_service` are still in the backend, but the
frontend no longer calls them.

### Phases 3 & 4 — **NOT STARTED**

Unchanged.

---

### Expert elicitation — **SHIPPED, not yet usable from the UI** *(new, 2026-09-21 → 09-24)*

This was never a roadmap phase. It grew out of the methods work in the
separate `advandeb_methods` repository: a consensus methodology for
multi-agent adjudication of evidence, with expert validation. What shipped:
- a panel/contributor tier model;
- a server-side calibration gate;
- public enrolment and admin review;
- the evidence-scoring task;
- expert DOI references with a retrieval-recall measurement.

See `docs/ELICITATION.md`. The frontend and API disagree on several
payloads, so the flows break in the browser (C19).

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
- *(added 2026-10-28)* **Default chat on a shared external model.** Users
  without their own key chat with NVIDIA Nemotron on one operator key
  (`DEFAULT_CHAT_*`), rate-limited across all users. NVIDIA was also added as
  a BYOK provider, with key validation (`c869ab8`).
- *(added 2026-10-28)* **KAG pipeline and EvidenceRegistry** — the in-backend
  answer path with stable `[n]` / `[G]` / `[SF]` / `[D]` citation markers
  (`SYSTEM-OVERVIEW.md` §4a).
- *(added 2026-10-28)* **The `reproduction` graph schema and pipeline** —
  extraction over OpenAlex reproduction abstracts
  (`knowledge_graph_scheme_descriptions.md`).
- *(added 2026-10-28)* **Curator review queues** over machine-generated output
  (`8c5ee08`), and the **`sf_elicitation` capability**, the first capability
  actually enforced.
- *(added 2026-10-28)* **Public landing page** (`0f1c24d`, 2026-05-21). It was
  listed as missing on 2026-08-26 but had existed since May.

---

## 4. Previous quarter — Q3 2026 (as written 2026-08-26)

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

## 4a. Current quarter — Q4 2026 (status, no new goals)

**The goals for this quarter have not been set.** The goals discussion has
not concluded. This section records where the Q3 goals ended up and which
decisions are open, so that discussion starts from facts. Ordering and
acceptance criteria stay in `docs/PLAN-2026-08-26.md`.

**Where the five Q3 goals stand (2026-10-28):**

| Q3 goal | State |
|---|---|
| 1. Close the CI blind spot | **Not closed, and worse.** All three CI jobs fail on `main`, and the KB job still ends in `\|\| true` (C1). |
| 2. Public face | **Landing page exists** (since May). The anonymous-read decision (C6) is still open. The first unauthenticated *write* path now exists: elicitation enrolment. |
| 3. Finish or abandon the Mongo→Arango migration | **Open** (C18). One part moved without being recorded: the graph views no longer use Mongo `graph_nodes` / `graph_edges` at all. |
| 4. Durable provenance | **Open** (C3). Nothing writes `provenance_traces`. |
| 5. Re-measure performance | **Not done.** |

**What actually consumed the quarter:**
- the tDEB simulator and model library;
- expert elicitation;
- BYOK and default-chat reliability fixes;
- the reproduction corpus and graph;
- a production data-loss incident (September, `STORAGE-CONTRACT.md` §2a).

**Decisions waiting on the goals discussion:**
- C6: open or closed knowledge base.
- C16: a licence is deferred by decision (2026-10-28) while the repository
  stays publicly visible.
- C18: finish the migration, or formally keep the transitional database.
- Whether elicitation, and the methods paper it serves, is the quarter's
  primary goal.
- The MongoDB network exposure (C20).

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
