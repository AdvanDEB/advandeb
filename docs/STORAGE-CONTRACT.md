# AdvanDEB Storage Contract

> **Written 2026-08-26**, from the running system. This document answers one
> question: **for any given entity, which store owns it, what derives from it,
> and how stale can the derivatives be?**
>
> It exists because AdvanDEB spreads overlapping data across four stores whose
> counts disagree in almost every row, and until now nothing recorded which one
> was authoritative.

---

## 1. The stores

| Store | Location | Role |
|---|---|---|
| **ArangoDB** `advandeb_kb` | `127.0.0.1:8529` | **Canonical knowledge store.** Documents, chunks, facts, stylized facts, taxa, and the graph edges between them. |
| **ChromaDB** | `data/chromadb` (17 GB) | **Canonical vector store.** Chunk embeddings for semantic retrieval. Collection name from `CHROMA_COLLECTION`. |
| **MongoDB** `advandeb` | `:27017` | **Canonical application store.** Users, auth, chat, LLM keys, audit logs, submissions. Also holds the *materialized* graph the frontend renders. |
| **MongoDB** `advandeb_knowledge_builder_kb` | `:27017` | **Transitional.** Migration remnant — see §2. |

### The Ollama and MCP layers hold no durable state

Ollama (`:11434`) and the Rust MCP gateway (`:8080`) are stateless with respect
to this contract. Agent working state lives in `agent_memory` / `agent_sessions`
in `advandeb`.

---

## 2. The second Mongo database is a migration remnant, not a design

`app/backend/app/core/config.py:61` says so explicitly:

```python
# Transitional: KB_DB_NAME used during MongoDB→ArangoDB migration. Remove after migration.
KB_DB_NAME: str = "advandeb_knowledge_builder_kb"
```

This is the single most important fact in this document. The `advandeb_knowledge_builder_kb`
database is the **old** knowledge store, mid-migration to ArangoDB. It is not a
second tier, not a cache, and not a staging area. It is the previous generation,
still present and still written to.

That explains every count mismatch:

| Entity | Mongo `advandeb` | Mongo `..._kb` | ArangoDB |
|---|---:|---:|---:|
| documents | 1,695 | 1,305 | 3,899,789 |
| facts | 28,309 | 63,709 | 109,395 |
| stylized_facts | 1,236 | 1,236 | 1,236 |
| chunks | — | 263,691 | 3,077,659 |
| graph nodes (materialized) | 49,700 | 102,060 | n/a |
| graph edges (materialized) | 70,724 | 155,397 | n/a |
| taxonomy | 1,258,523 | 1,257,912 | 1,257,912 |

These are three generations of the same corpus at three different points in the
migration, not three views of one dataset.

**What still reads or writes the transitional database** (verified callers of
`get_kb_database()`):

- `main.py:111` — `batch_watchdog` ingestion-batch state
- `api/routes/kb/ingestion.py` — the entire ingestion workflow surface
- `api/routes/kb/visualization.py` — graph artifact reads and `GraphArtifactStore`
- `services/user_submission_service.py:204` — user submissions
- `services/provenance_service.py:54` — document-metadata **fallback** only

`core/database.py:17` describes it as "ingestion workflow state only." That
description is now inaccurate — visualization artifacts and user submissions
also live there.

**Contract:** treat `advandeb_knowledge_builder_kb` as **read-mostly legacy**.
Do not add new writers. Every new knowledge write goes to ArangoDB; every new
application write goes to `advandeb`.

---

## 3. Ownership table

| Entity | Authoritative store | Derived copies | Sync trigger | Staleness tolerance |
|---|---|---|---|---|
| **Users, roles, sessions** | Mongo `advandeb` | none | — | none — strongly consistent |
| **Auth tokens / revocations** | Mongo `advandeb` (`revoked_tokens`, TTL) | none | — | none |
| **Chat sessions & messages** | Mongo `advandeb` | `chatbot` materialized schema (KB db) | `mark_dirty("chatbot")` on every message | minutes |
| **BYOK LLM keys** | Mongo `advandeb` (`user_llm_keys`) | none | — | none |
| **Documents (curated)** | ArangoDB `document_meta` + `documents` | Mongo `advandeb.documents`, Mongo KB `documents` | ingestion pipeline | hours — migration-dependent |
| **Document full text / chunks** | ArangoDB `chunks` | Mongo KB `chunks` (legacy) | ingestion | legacy copy is frozen |
| **Chunk embeddings** | **ChromaDB** | none | ingestion / re-embed scripts | none — retrieval reads it directly |
| **Facts** | ArangoDB `facts` | Mongo `advandeb.facts`, Mongo KB `facts` | ingestion + extraction | hours |
| **Stylized facts** | ArangoDB `stylized_facts` | Mongo (both, 1,236 each — in agreement) | seeded, rarely changes | days |
| **Fact→SF support** | ArangoDB `sf_support` | `fact_sf_relations` (both Mongo dbs), `sf_support` materialized schema | extraction | minutes–hours |
| **Taxonomy** | ArangoDB `taxa` / `taxonomical` | `taxonomy_nodes` (both Mongo dbs) | taxonomy import | days — changes rarely |
| **Citations** | ArangoDB `citations` | `citation` materialized schema | ingestion | hours |
| **Materialized graphs** | **Mongo `graph_nodes` / `graph_edges`** | none — they *are* the derivative | `GraphRebuildQueue` | see §4 |
| **Provenance** | **nothing — not persisted** | — | — | see §5 |

---

## 4. The materialization path

The Cosmograph frontend never reads ArangoDB. It reads `graph_nodes` /
`graph_edges` in MongoDB, keyed by `schema_id`, built by
`GraphArtifactBuilder` and driven by `GraphRebuildQueue`.

**Trigger:** `graph_rebuild_queue.mark_dirty(<schema>)`. All live callers:

| Schema marked dirty | Called from |
|---|---|
| `chatbot` | `chat_service.py` (×5), `ws.py:148` — i.e. **on every chat message** |
| `sf_support` | `kb/pipeline.py:1497` |
| `citation` | `kb/pipeline.py:1498` |
| `knowledge_graph` | `kb/pipeline.py:1643`, `:1660` |
| `taxonomical` | **never** |
| `physiological_process` | **never** |

**Pacing** (`graph_rebuild_queue.py:25-26`, overridable via
`GRAPH_ARTIFACT_REBUILD_*` in app config):

- `SETTLE_DELAY_SECONDS = 5.0` — coalesces a burst of `mark_dirty()` into one rebuild
- `MIN_REBUILD_INTERVAL_SECONDS = 120.0` — floor between two rebuilds of the same schema

The pacing is load-bearing, and the code says why: chat marks `chatbot` dirty
per message, and without a floor the worker runs back-to-back full-graph
rebuilds, each loading the entire graph and running a force layout — pinning a
CPU and ratcheting RSS. **Do not remove or shorten the interval without
re-testing memory behaviour.**

**Contract:**
- Materialized graphs are **eventually consistent, floor 2 minutes.**
- They are **fully rebuildable** — safe to drop and regenerate.
- `taxonomical` and `physiological_process` have no trigger. `taxonomical` is
  populated (15,948 edges) but only ever refreshes via a manual/scripted path;
  `physiological_process` is empty and stays empty.
- The queue runs on the **primary worker only** (`main.py:107`, gated by
  `_is_primary_worker()`). Under multiple workers this election is a heuristic,
  not a lease — tracked as C13 in `docs/PLAN-2026-08-26.md`.

---

## 5. Provenance is not persisted

`provenance_traces` in ArangoDB holds **0 documents**, and nothing writes to it:

- `GraphExpansionService.store_provenance_trace()` — no production callers
- `SynthesisAgent._build_provenance()` — docstring: *"not stored — caller decides"*; no caller stores it
- `ProvenanceService.get_provenance()` — queries `provenance_traces` first, always misses, falls through to `_reconstruct_provenance()`

**Contract, as it stands today:** provenance has **no authoritative store**. It
is reconstructed on read from `chunks` / `facts` / `stylized_facts`, against the
corpus *as it exists at read time*.

The consequence is worth stating plainly: **an answer's evidence chain cannot be
audited after the fact.** Re-opening a six-month-old conversation re-derives what
the evidence would be today, not what it was. For a research tool whose stated
purpose is eliminating hallucination through full provenance, this should be a
deliberate decision rather than an accident. Tracked as C3.

---

## 6. Rules for new code

1. **New knowledge writes go to ArangoDB.** Never add a writer to
   `advandeb_knowledge_builder_kb`.
2. **New application writes go to Mongo `advandeb`.**
3. **Never write `graph_nodes` / `graph_edges` directly.** Mark the schema dirty
   and let `GraphArtifactBuilder` own the shape.
4. **Never read ArangoDB from the frontend path.** Go through the materialized
   schema or the artifact store, so the pacing floor stays meaningful.
5. **If you add a schema, add its `mark_dirty()` trigger in the same change.**
   `physiological_process` is the cautionary example: registered, never
   triggered, permanently empty, and documented for months as though it worked.
6. **If a count surprises you, check which generation you are reading** before
   concluding there is a bug.

---

## 7. Open items

Tracked in `docs/PLAN-2026-08-26.md`:

- **Finish or formally abandon the Mongo→Arango migration.** The transitional
  database has outlived its comment. Either complete the cutover and drop it, or
  promote it to a documented tier with an owner. The present half-state is what
  makes every count in §2 unexplainable without this document.
- **C3** — decide whether provenance becomes durable.
- **C13** — replace `_is_primary_worker()` with a Mongo lease before running
  multiple workers, or the rebuild queue may run twice.
- Reconcile the two `Settings` objects (`app.core.config` and
  `advandeb_kb.config.settings`), which independently define database names —
  `DATABASE_NAME` in the KB settings defaults to the *transitional* database,
  while `CHAT_STORE_DB_NAME` points back at `advandeb`.
