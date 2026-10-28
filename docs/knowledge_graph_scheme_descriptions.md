# Knowledge Graph Scheme Descriptions

> **Reconciled 2026-08-26** against the live ArangoDB `advandeb_kb` instance and
> the `graph_schemas` registrations in both MongoDB databases. Every collection,
> edge definition, and named graph below was read from the running system.
>
> **Updated 2026-10-28** from the code. Changes:
> - added the `reproduction` schema, registered since `c828adc` (2026-06-21)
>   and previously undocumented;
> - corrected the schema registry;
> - corrected the `mark_dirty` triggers;
> - removed the contradiction between the 35- and 6,003-edge `knowledge_graph`
>   counts.
>
> Live counts were **not** re-taken on 2026-10-28; every count below is dated.

## Read this first: there are two graph layers

The previous revision of this document described a single "knowledge graph."
There are actually **two distinct layers**, and conflating them is the source of
most confusion when reading the code:

| | **Canonical layer** | **Materialized layer (graph artifacts)** |
|---|---|---|
| Store | ArangoDB `advandeb_kb` | gzipped JSON files under `GRAPH_ARTIFACT_DIR` (default `data/graph_artifacts`); metadata in `graph_artifact_meta` in Mongo `advandeb_knowledge_builder_kb` |
| Organised by | *named graphs* over edge collections | *schemas* from the static `BUILTIN_SCHEMAS`, keyed by `schema_id` |
| Written by | ingestion, KG builder, taxonomy import | `GraphArtifactBuilder`, driven by `GraphRebuildQueue` — it fetches from ArangoDB (`graph_query_fetchers.py`) and lays out with NetworkX |
| Read by | agents, retrieval, provenance reconstruction | the Cosmograph frontend canvas, via `/api/kb/viz/...` |
| Source of truth | **yes** | no — derived, rebuildable |

> **Correction (2026-10-28).** Earlier revisions, including the 2026-08-26
> reconciliation, said the materialized layer is MongoDB `graph_nodes` /
> `graph_edges`, registered in `graph_schemas`, and built from Mongo source
> collections. **The code no longer works that way.**
> `advandeb_kb/services/graph_query_service.py` states it outright: *"No
> graph_schemas / graph_nodes / graph_edges MongoDB collections needed."*
>
> - Every schema except `chatbot` is fetched from **ArangoDB**.
> - `chatbot` reads Mongo chat sessions, plus Arango lookups.
> - No backend or KB code reads or writes the Mongo `graph_nodes`,
>   `graph_edges` or `graph_schemas` collections any more.
>
> Their live counts below were taken from data left over in Mongo. They
> describe that legacy data, **not** what the canvas renders. The per-schema
> node and edge vocabulary is still accurate. Where Layer 2 says "Mongo
> source", read "the Arango fetcher for that schema".

Some names appear in both layers with **different content**;
`knowledge_graph` is the sharpest example. Some exist in only one:
`chunk_graph` is Arango-only, while `physiological_process`, `chatbot` and
`reproduction` exist only as schemas. Always state which layer you mean.

**One correction to the table above.** The `knowledge_graph` and
`reproduction` schemas now build their artifacts **from ArangoDB**, through
`graph_query_fetchers.py`. The table's "materialized layer reads Mongo" rule
holds only for the older schemas.

---

# Layer 1 — ArangoDB (canonical)

## Document collections

| Collection | Live count | Description |
|---|---:|---|
| `documents` | 3,899,789 | Scientific papers and ingested sources. The large count is the broad literature index; the curated, fully-processed set is `document_meta`. |
| `chunks` | 3,077,659 | Fixed-size text windows over document content, carrying vector embeddings. Spans 603,739 distinct documents. |
| `taxa` | 1,257,912 | NCBI taxonomy units, supplemented by GBIF. |
| `facts` | 109,395 | Factual observations extracted from documents. Spans 11,913 distinct documents. |
| `document_meta` | 1,253 | Metadata for the curated ingested paper set. |
| `stylized_facts` | 1,236 | General biological principles — the conceptual backbone. |
| `provenance_traces` | **0** | See "Provenance" below. Dead schema. |

Full-text indexes: `documents.content`, `documents.abstract`, `facts.text`,
`stylized_facts.description`, `chunks.text`. These back the keyword half of
`HybridRetrievalService`'s RRF fusion.

## Edge collections

| Collection | Live count | From → To |
|---|---:|---|
| `chunk_belongs_to` | 2,464,969 | `chunks` → `documents` |
| `taxonomical` | 1,257,912 | `taxa` → `taxa` (parent) |
| `sf_support` | 31,311 | `facts` → `stylized_facts` |
| `citations` | 8,521 | `documents` → `documents` |
| `knowledge_graph` | 6,003 | `documents`, `facts` → `taxa`, `stylized_facts` |

**`knowledge_graph` held only 35 edges until 2026-08-26.** Despite the name, the
integrated cross-entity graph users actually see is the *materialized*
`knowledge_graph` schema in Layer 2, which is built from Mongo relation
collections rather than from this Arango edge collection. Do not assume this
collection is the integrated graph.

### Why it was empty, and what changed (2026-08-26)

All 35 edges shared one timestamp — `2026-05-27T14:27:41` — a single manual run.
Three compounding causes, all now fixed:

1. **The name index was restricted to mammals.** `root_taxid` defaulted to
   40674 (Mammalia) at every entry point, so the index held 14,469 of 1,257,912
   taxa — 1.15% of the vocabulary. Measured over 20,000 titles, 88% of species
   mentions in this corpus are non-mammalian (ray-finned fishes outnumber
   mammals roughly 4:1). Every one of the 28 linked taxa was a mammal. The
   default is now `None` — index the whole taxonomy.
2. **The candidate regex was greedy.** `_BINOMIAL_RE` captures a capitalised
   word plus up to two following lowercase words, so "Growth of Danio rerio
   under stress" yielded `"Danio rerio under"` and matched nothing. Names were
   only found when they happened to end a phrase. `_candidate_names` now emits
   every leading sub-phrase of each capture.
3. **Nothing triggered it.** The only callers were the HTTP routes and a
   standalone script. Linking is now hooked into `_update_batch_status`, so an
   ingestion batch links its own documents on completion.

Because the index went from 14k mammal names to 1.5M entries, matching needed a
precision guard — see `_AMBIGUOUS_TAXON_NAMES` and `_SINGLE_TOKEN_RANKS` in
`kg_builder_service.py`. Multi-word names are accepted anywhere; a bare
capitalised word must resolve to genus-or-below and must not be an English
homograph. Without it the crab genus *Cancer* claimed 90 oncology papers per
40,000 titles, and the moth genus *Data* claimed 27.

Result: **35 → 6,003 edges, 22 → 3,171 documents, 28 → 2,659 distinct taxa.**
Of the curated `document_meta` set, 557 of 1,253 papers (44%) now carry a link.
All edges are written with `status: "suggested"` for curator review, and the
`evidence` field records the matched text.

The backfill covered the `curated` and `with_facts` scopes. The remaining ~3.9M
OpenAlex abstract records have **not** been linked — see the scope note below.

## Named graphs

Declared in `advandeb_kb/database/arango_client.py` and verified identical in
the live instance:

| Named graph | Edge collection | From → To |
|---|---|---|
| `citation_graph` | `citations` | `documents` → `documents` |
| `support_graph` | `sf_support` | `facts` → `stylized_facts` |
| `taxonomy_graph` | `taxonomical` | `taxa` → `taxa` |
| `knowledge_graph` | `knowledge_graph` | `documents`, `facts` → `taxa`, `stylized_facts` |
| `chunk_graph` | `chunk_belongs_to` | `chunks` → `documents` |

**Correction to the previous revision:** it described `support_graph` as
containing `documents` nodes and an `extracted_from` edge. It does not.
`support_graph` is a single edge definition, `facts → stylized_facts`. There is
no `extracted_from` edge collection in ArangoDB at all — `extracted_from` exists
only as a materialized edge type in Layer 2.

## Provenance

`provenance_traces` holds **zero documents**, and this is not a data gap — it is
the designed-but-unwired state:

- `GraphExpansionService.store_provenance_trace()` and `build_provenance_trace()`
  have **no production callers**. Only the model definition and a test reference
  them.
- `SynthesisAgent._build_provenance()` carries the docstring *"Build a
  serialisable provenance dict (not stored — caller decides)"*. No caller stores it.
- `ProvenanceService.get_provenance()` queries `provenance_traces` first, always
  misses, and falls through to `_reconstruct_provenance()`, which rebuilds the
  chain live from `chunks` / `facts` / `stylized_facts`.

**Consequence:** provenance is *reconstructed*, never *recorded*. The trail panel
works, but you cannot later audit which evidence produced a given historical
answer — only re-derive what evidence would be found now, against a corpus that
has since changed. For a system whose founding goal was eliminating
hallucination through full provenance tracking, this is a substantive gap. It is
tracked as C3 in `docs/PLAN-2026-08-26.md`.

---

# Layer 2 — Materialized schemas (graph artifacts)

Each schema is built into one **artifact**:
- **Builder:** `GraphArtifactBuilder`. It runs the schema's fetcher in
  `graph_query_fetchers.py`, computes degrees, and lays the graph out with
  NetworkX.
- **Storage:** `GraphArtifactStore` writes the result as a gzipped JSON file
  under `GRAPH_ARTIFACT_DIR`. Its metadata goes in `graph_artifact_meta` in
  Mongo `advandeb_knowledge_builder_kb`.
- **Reading:** the frontend loads it through `/api/kb/viz/schema/{id}/artifact`
  (and `/snapshot`, `/overview`, `/stream`).

**Node fields:** `node_type`, `entity_collection`, `entity_id`, `label`,
`properties` (including `cluster_id`), `degree`, `x2d`/`y2d`.
**Edge fields:** `edge_type`, source, target, `weight`, `properties`.

`GRAPH_ARTIFACT_LAYOUT_NAME` (currently `schema_default_v4`) stamps the layout functions. If an artifact's
version does not match, the frontend falls back to a force simulation.

Schema definitions in `BUILTIN_SCHEMAS` still name "source collections" such
as `taxonomy_nodes`. Those names are vocabulary left over from the Mongo era.
The fetchers read the Arango collections (`taxa`, `documents`, `facts`, …).
See the correction under "Read this first".

## Registered schemas

Schemas are **static**: they come from `BUILTIN_SCHEMAS` in
`knowledge-builder/advandeb_kb/models/graph.py`. The API accepts exactly
these seven (`VALID_SCHEMAS` in `app/backend/app/api/routes/kb/visualization.py`).
`POST /api/kb/viz/seed` is a no-op kept for the frontend.

| Schema | Source of its artifact | Rebuild trigger (`mark_dirty`) |
|---|---|---|
| `citation` | Arango (`fetch_citation`) | ingestion (`kb/pipeline.py`), `knowledge_service.py` |
| `sf_support` | Arango (`fetch_sf_support`) | ingestion (`kb/pipeline.py`) |
| `taxonomical` | Arango (`fetch_taxonomical`), `taxa` scoped by `knowledge_graph` | KG builder (`kb/pipeline.py`) |
| `knowledge_graph` | Arango (`fetch_knowledge_graph`) | ingestion + KG builder (`kb/pipeline.py`) |
| `physiological_process` | Arango (`fetch_physiological`) — see its section | KG builder (`kb/pipeline.py`) |
| `chatbot` | Mongo chat sessions + Arango lookups (`fetch_chatbot_graph`) | every chat message (`chat_service.py`, `ws.py`) |
| `reproduction` | Arango (`fetch_reproduction`) | **none** — only a manual rebuild |

`knowledge-builder/tests/test_models.py::test_builtin_schemas` still asserts
five schemas and fails. That is part of C1 in the plan.

For the record, the 2026-08-26 audit found these legacy registrations in the
Mongo `graph_schemas` collections. No code reads them any more:

| Schema | `advandeb` | `advandeb_knowledge_builder_kb` |
|---|:---:|:---:|
| `citation` | ✓ | ✓ |
| `sf_support` | ✓ | ✓ |
| `taxonomical` | ✓ | ✓ |
| `knowledge_graph` | ✓ | ✓ |
| `physiological_process` | ✓ | ✓ |
| `chatbot` | — | ✓ |

## What each schema actually materializes

### `sf_support` — the evidence network
Nodes: `document`, `fact`, `stylized_fact`.
Edges: `extracted_from` (fact → document), `supports` / `opposes`
(fact → stylized_fact).

Live: 28,309 `extracted_from`, 22,370 `supports`, 1,016 `opposes` in `advandeb`;
63,679 / 29,707 / 1,604 in the KB database.

An undeclared **`neutral`** edge type also exists (4 edges in `advandeb`). The
schema declares only `supports` and `opposes`. Either the vocabulary should gain
`neutral` or those 4 edges are stray.

### `citation` — the citation network
Nodes: `document`, plus `external_document` ghost nodes for cited-but-not-ingested DOIs.
Edges: `cites`.

Live: 1,736 `cites` and **0** ghost nodes in `advandeb`; 60,012 `cites` and
34,149 `external_document` ghost nodes in the KB database. The citation network
is overwhelmingly a KB-database artifact; the app-facing copy is a thin subset.

Edge-building runs in two phases — DOI-based from each document's `references`
field (`method: "doi"`, `internal: true|false`), falling back to taxon-overlap
Jaccard similarity (`method: "taxon_overlap"`, threshold ≥ 0.2, top-5 peers)
when fewer than 10 DOI edges are produced.

### `taxonomical` — the organisms the corpus studies
Nodes: rank-typed taxa (`kingdom`, `phylum`, `class`, `order`, `family`,
`genus`, `species`, `clade`). Edges: `is_child_of`.
Live: 15,948 `is_child_of` edges in `advandeb`.

**Scope change (2026-08-26):** this schema no longer materializes the whole
`taxa` collection. That collection is a full NCBI backbone import — 1,257,912
rows — which exists so ingestion can resolve any organism name it meets. Served
as a graph it produced a 40 MB artifact and 1.3M undifferentiated dots.

The schema now materializes the taxa referenced by `knowledge_graph` edges
(documents that study an organism) plus every ancestor on their `lineage`; the
ancestors are what make the result a connected tree instead of a scatter of
unrelated species. Referenced taxa carry `properties.studied = true` and are
drawn larger than the lineage scaffolding around them.

When this scope change shipped, the result was 123 nodes / 122 edges from 28
studied taxa. That was **before** the same-day `knowledge_graph` backfill,
which raised the number of distinct linked taxa to 2,659. The materialized
count has not been re-measured since; expect it to be far larger. It grows as
the KG builder runs.

If nothing references a taxon yet, it falls back to the rank backbone down to
family (capped at 10,000 nodes) so the view is an orientation aid rather than
empty.

`node_type` is the taxon's major rank rather than the generic `taxon`, so the
sidebar offers a per-rank filter and the canvas colours by rank. NCBI's ~40 rank
strings are collapsed onto the eight above (`subspecies` → `species`,
`superfamily` → `family`, `no rank` → `clade`, …); see `taxon_node_type` in
`graph_query_serialization.py`. `entity_collection` stays `taxa` regardless.

Layout is a radial dendrogram — root at the centre, one ring per level, angular
span divided by leaf count. The previous tidy tree put cumulative leaf offsets
on X and depth on Y, giving a bounding box 67,000,000 units wide and 3,400 tall.

### `knowledge_graph` — the integrated graph
Nodes: `taxon` (materialized with `node_type` set to the taxon's **rank** —
`species`, `genus`, `family`, … — for visual differentiation), `document`.
Edges: `is_child_of`, `studies` (document → taxon, via `document_taxon_relations`).

Live in `advandeb`: 14,469 generic `taxon` nodes plus rank-typed nodes (352
species, 311 genus, 214 family, 100 order, 90 clade, …), 4,205 documents, 1,341
`studies` edges. **The KB database has no taxon nodes materialized at all** —
this schema is meaningfully populated only in `advandeb`.

Every node carries `properties.cluster_id` for frontend cluster colouring:
`sf:<category>`, `fact`, `doc:<general_domain>`, `taxon:<rank>`, `external`.

**Scope note (2026-04-01):** the taxonomy root moved from Mammalia (40674) to
Animalia (33208), with a materialization cap of 100,000 nodes. The cap is a
ceiling, not a description — actual materialized taxon nodes are ~16,000.

**Scope change (2026-08-26):** the Arango-backed artifact behind this schema no
longer takes a blind `LIMIT` slice of each collection. `fetch_knowledge_graph`
used to load `GRAPH_ARTIFACT_MAX_NODES // 4` = 12,500 rows from each of
`documents` (3.9M), `facts` (109k), `stylized_facts` and `taxa` (1.26M). An edge
only survives if **both** endpoints land inside their slice, so the rarest edge
type is the one that disappears: of the 35 `studies` edges — spanning 22
documents and 28 taxa nowhere near the front of a 3.9M / 1.26M scan — exactly
**one** survived, in a graph whose entire point is the document→organism link.

Each collection is now scoped to what actually carries an edge (`_KG_SCOPE_AQL`
in `graph_query_fetchers.py`):

| Layer | Selection | Count |
|---|---|---:|
| `taxa` | referenced by `knowledge_graph` edges + their `lineage` ancestors | 123 (pre-backfill) |
| `documents` | `knowledge_graph` endpoints ∪ `citations` endpoints ∪ source docs of the selected facts | 1,213 |
| `facts` | `knowledge_graph` endpoints ∪ those with an `sf_support` edge | 18,053 |
| `stylized_facts` | all | 1,236 |

`facts` is the only layer that can realistically outgrow the node budget, so it
is the only one that keeps a cap; documents are derived from the facts that
survive it, which keeps `extracted_from` whole. Lineage tax_ids absent from the
NCBI import (1, 131567, 2759, 33154) are dropped via `DOCUMENT()`, which skips
keys with no row.

Artifact went from 38,736 nodes / 8,427 edges to **20,625 nodes / 57,920
edges**. It got smaller because every node now participates in the graph, and
far denser because no edge type is truncated any more:
- 35/35 `studies`;
- 8,521/8,521 `cites`;
- 31,311/31,311 `supports` + `opposes`;
- plus 18,053 `extracted_from`.

All of this was measured **before** the `knowledge_graph` backfill
(35 → 6,003 edges). The layer counts and artifact size above are the
pre-backfill figures.

### `physiological_process` — registered, materializes nothing
Nodes: `stylized_fact`, `taxon`.
Edges: `regulates`, `depends_on` (sf → sf), `exhibited_by` (sf → taxon).

**Live count of all three edge types in the legacy Mongo layer: zero, in both
databases.** The old builder sourced them from `sf_sf_relations` and
`sf_taxon_relations`, and neither collection exists in either database.

The current Arango fetcher (`fetch_physiological`) takes a different route.
It derives `exhibited_by` (stylized fact → taxon) through
`sf_support` → `facts` → documents → `knowledge_graph` → `taxa`. It can
therefore produce edges now that `knowledge_graph` holds 6,003 links.
`regulates` / `depends_on` still have no source. The artifact's current size
has **not** been checked. Since 2026-08-29 the KG-builder pipeline marks the
schema dirty. The previous revision hedged this with "if
it exists"; the answer is that they do not. This schema is aspirational — it
should either be built or withdrawn, not left registered and empty.

### `reproduction` — the reproduction-domain subgraph
Registered since `c828adc` (2026-06-21); undocumented until 2026-10-28. Built
from **ArangoDB** by `fetch_reproduction` (`graph_query_fetchers.py`), through
the same edge collections the canonical layer uses: `citations`, `sf_support`
and `knowledge_graph`.

**Scope.** Documents with `general_domain == 'reproduction'` **and**
`processing_status == 'completed'`, plus:
- the facts extracted from them;
- the stylized facts those facts support or oppose;
- the taxa the documents study, with their full lineage.

The domain tag alone does not narrow anything. Nearly the whole literature
index carries it: 3,898,536 of 3,899,789 documents, the exceptions being the
1,253 curated papers. `processing_status` is the real selector, and in
August it bounded the set to ~10.7k abstracts.

**Nodes:**

| Node type | Source | Meaning |
|---|---|---|
| `document` | `documents` | reproduction-domain paper |
| `abstract` | `documents` | abstract-only record from the OpenAlex import (`source_type='web'`) |
| `conclusion` | `facts` (`fact_type='conclusion'`) | the abstract's main finding |
| `background_knowledge` | `facts` (`fact_type='background_knowledge'`) | what the abstract assumes from prior work, not its own result |
| `citation` | `facts` (`fact_type='citation'`) | another work the abstract refers to |
| `stylized_fact` | `stylized_facts` | a stylized fact supported or opposed by a reproduction fact |
| `taxon` | `taxa` | organism studied; `properties.studied = true` for directly linked taxa, lineage ancestors otherwise |

**Edges:** `cites`, `extracted_from`, `supports`, `opposes`, `studies`.

**How the data gets there.** Scripts in `knowledge-builder/scripts/`, run by
hand:
1. `import_reproduction_abstracts.py` imports the OpenAlex corpus into Arango
   `documents` as `pending`.
2. `filter_reproduction_abstracts.py` applies a two-stage domain-relevance
   filter.
3. `run_reproduction_pipeline.py` makes one small-model Ollama call per
   abstract and extracts a conclusion, background knowledge and citations as
   `facts` with a `fact_type`. It is resumable and deduplicates by content
   fingerprint. It has been run with `OLLAMA_MODEL=gemma2:2b`, the small model
   that fits the host's memory.
4. `embed_reproduction_abstracts.py` chunks and embeds the abstracts so chat
   can retrieve them.

`backfill_domain_gate.py` applies the domain gate retroactively.
`scripts/rebuild_repro_index.py` and `scripts/check_repro_coverage.py` (repo
root) maintain and audit the reproduction vector-index cache.

**Rebuild.** Nothing calls `mark_dirty("reproduction")`. The artifact changes
only when someone rebuilds it from the KB drawer, or with
`POST /api/kb/viz/schema/reproduction/rebuild`. Rule 5 of
`docs/STORAGE-CONTRACT.md` §6 says a schema must ship with its trigger; this
one did not.

### `chatbot` — previously undocumented
Present only in `advandeb_knowledge_builder_kb`. Projects chat activity onto the
knowledge graph.

Nodes: `user`, `chat_session`, `document`, `fact`, `stylized_fact`, `taxon`.
Edges: `has_session` (user → session), `references_document`, `references_fact`,
`references_stylized_fact`, `references_taxon` (all session → entity).

Live: 16 sessions, 3 users, 283 `references_fact`, 89
`references_stylized_fact`, 16 `has_session`, 7 `references_document`.

---

## Node type reference

Properties below are the fields the materializer projects, per the registered
schema definitions.

| Node type | Source collection | Label field | Projected properties |
|---|---|---|---|
| `document` | `documents` | `title` | `doi`, `year`, `authors`, `journal`, `general_domain` |
| `fact` | `facts` | `content` | `general_domain`, `confidence`, `status` |
| `stylized_fact` | `stylized_facts` | `statement` | `category`, `status` |
| `taxon` (and rank-typed variants) | `taxonomy_nodes` | `name` | `rank`, `tax_id`, `gbif_usage_key`, `common_names` |
| `chunk` | `chunks` (Arango only) | — | `chunk_id`, `document_id`, `chunk_index`, `text`, `char_start`, `char_end`, `embedded` |
| `external_document` | synthesised ghost node | `doi` | `doi`, `internal: false`, `cluster_id: "external"` |
| `user` / `chat_session` | `chat_sessions` | `user_id` / `title` | `user_id`, `created_at` |
| `abstract` | `documents` (reproduction) | `title` | `doi`, `year`, `authors`, `journal`, `general_domain` |
| `conclusion` / `background_knowledge` / `citation` | `facts` by `fact_type` (reproduction) | `content` | `confidence`, `status`, `document_id`, `fact_type` |

## Edge type reference

| Edge type | From → To | Layer | Live? |
|---|---|---|---|
| `chunk_belongs_to` / `has_chunk` | chunk → document | Arango | ✓ 2.46M |
| `is_child_of` | taxon → taxon | both | ✓ |
| `supports` / `opposes` | fact → stylized_fact | both (`sf_support` in Arango) | ✓ |
| `extracted_from` | fact → document | **materialized only** | ✓ |
| `cites` | document → document / external_document | both | ✓ |
| `studies` | document → taxon | Arango `knowledge_graph` edges (6,003 incl. fact links, 2026-08-26); materialized in `knowledge_graph`, `taxonomical`, `reproduction` | ✓ |
| `neutral` | fact → stylized_fact | materialized, **undeclared** | ⚠ 4 |
| `regulates` / `depends_on` / `exhibited_by` | sf → sf / sf → taxon | materialized only | ✗ **0** |
| `has_session` / `references_*` | chat session → entity | materialized only (`chatbot`) | ✓ |

---

## Open questions this reconciliation raised

Tracked in `docs/PLAN-2026-08-26.md`:

1. `provenance_traces` is dead schema and provenance is not durable (C3).
2. `physiological_process` is registered but materializes nothing.
3. The Arango `knowledge_graph` edge collection (6,003 edges since the
   2026-08-26 backfill; 35 before) and the materialized `knowledge_graph`
   schema share a name but not content.
4. The `neutral` edge type is undeclared in the `sf_support` schema vocabulary.
5. `reproduction` has no `mark_dirty` trigger (see its section).
6. `citation` and `knowledge_graph` are populated in different databases —
   citations mostly in the KB database, taxa only in `advandeb`. Which one the
   frontend reads for which view is not written down. See
   `docs/STORAGE-CONTRACT.md`.
