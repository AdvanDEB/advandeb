# Knowledge Graph Scheme Descriptions

> **Reconciled 2026-08-26** against the live ArangoDB `advandeb_kb` instance and
> the `graph_schemas` registrations in both MongoDB databases. Every collection,
> edge definition, and named graph below was read from the running system.

## Read this first: there are two graph layers

The previous revision of this document described a single "knowledge graph."
There are actually **two distinct layers**, and conflating them is the source of
most confusion when reading the code:

| | **Canonical layer** | **Materialized layer** |
|---|---|---|
| Store | ArangoDB `advandeb_kb` | MongoDB `graph_nodes` / `graph_edges` |
| Organised by | *named graphs* over edge collections | *schemas* registered in `graph_schemas`, keyed by `schema_id` |
| Written by | ingestion, KG builder, taxonomy import | `graph_artifact_builder` / `graph_snapshot_service` |
| Read by | agents, retrieval, provenance reconstruction | the Cosmograph frontend canvas |
| Source of truth | **yes** | no — derived, rebuildable |

Some names appear in both layers with **different content** (`knowledge_graph`
is the sharpest example). Some exist in only one (`chunk_graph` is Arango-only;
`physiological_process` and `chatbot` are materialized-only). Always state which
layer you mean.

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
| `knowledge_graph` | **35** | `documents`, `facts` → `taxa`, `stylized_facts` |

**`knowledge_graph` is effectively empty at 35 edges.** Despite the name, the
integrated cross-entity graph users actually see is the *materialized*
`knowledge_graph` schema in Layer 2, which is built from Mongo relation
collections rather than from this Arango edge collection. Do not assume this
collection is the integrated graph.

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

# Layer 2 — Materialized schemas (MongoDB)

Registered in `graph_schemas`; nodes and edges live in `graph_nodes` /
`graph_edges` tagged by `schema_id`.

**Node fields:** `schema_id`, `node_type`, `entity_collection`, `entity_id`,
`label`, `properties`, `degree`, `x`/`y`/`z`, `x2d`/`y2d`.
**Edge fields:** `schema_id`, `edge_type`, `source_node_id`, `target_node_id`,
`weight`, `properties`.

Note that schema definitions reference **Mongo** source collections
(`taxonomy_nodes`, `documents`, `facts`, …), not the Arango collections. The
materializer reads Mongo, not Arango.

## Registered schemas

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
drawn larger than the lineage scaffolding around them. Currently 123 nodes /
122 edges from 28 studied taxa, and it grows as the KG builder runs.

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
| `taxa` | referenced by `knowledge_graph` edges + their `lineage` ancestors | 123 |
| `documents` | `knowledge_graph` endpoints ∪ `citations` endpoints ∪ source docs of the selected facts | 1,213 |
| `facts` | `knowledge_graph` endpoints ∪ those with an `sf_support` edge | 18,053 |
| `stylized_facts` | all | 1,236 |

`facts` is the only layer that can realistically outgrow the node budget, so it
is the only one that keeps a cap; documents are derived from the facts that
survive it, which keeps `extracted_from` whole. Lineage tax_ids absent from the
NCBI import (1, 131567, 2759, 33154) are dropped via `DOCUMENT()`, which skips
keys with no row.

Artifact went from 38,736 nodes / 8,427 edges to **20,625 nodes / 57,920 edges**
— smaller because every node now participates in the graph, far denser because
no edge type is truncated any more: 35/35 `studies`, 8,521/8,521 `cites`,
31,311/31,311 `supports`+`opposes`, plus 18,053 `extracted_from`.

### `physiological_process` — registered, materializes nothing
Nodes: `stylized_fact`, `taxon`.
Edges: `regulates`, `depends_on` (sf → sf), `exhibited_by` (sf → taxon).

**Live count of all three edge types: zero, in both databases.** The builder
sources them from `sf_sf_relations` and `sf_taxon_relations`, and neither
collection exists in either database. The previous revision hedged this with "if
it exists"; the answer is that they do not. This schema is aspirational — it
should either be built or withdrawn, not left registered and empty.

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

## Edge type reference

| Edge type | From → To | Layer | Live? |
|---|---|---|---|
| `chunk_belongs_to` / `has_chunk` | chunk → document | Arango | ✓ 2.46M |
| `is_child_of` | taxon → taxon | both | ✓ |
| `supports` / `opposes` | fact → stylized_fact | both (`sf_support` in Arango) | ✓ |
| `extracted_from` | fact → document | **materialized only** | ✓ |
| `cites` | document → document / external_document | both | ✓ |
| `studies` | document → taxon | materialized only | ✓ 1,341 |
| `neutral` | fact → stylized_fact | materialized, **undeclared** | ⚠ 4 |
| `regulates` / `depends_on` / `exhibited_by` | sf → sf / sf → taxon | materialized only | ✗ **0** |
| `has_session` / `references_*` | chat session → entity | materialized only (`chatbot`) | ✓ |

---

## Open questions this reconciliation raised

Tracked in `docs/PLAN-2026-08-26.md`:

1. `provenance_traces` is dead schema and provenance is not durable (C3).
2. `physiological_process` is registered but materializes nothing.
3. The Arango `knowledge_graph` edge collection (35 edges) and the materialized
   `knowledge_graph` schema share a name but not content.
4. The `neutral` edge type is undeclared in the `sf_support` schema vocabulary.
5. `citation` and `knowledge_graph` are populated in different databases —
   citations mostly in the KB database, taxa only in `advandeb`. Which one the
   frontend reads for which view is not written down. See
   `docs/STORAGE-CONTRACT.md`.
