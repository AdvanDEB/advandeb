# Knowledge Graph Scheme Descriptions

This document describes the nodes, edges, and named graphs in the AdvanDEB knowledge graph.

---

## Node Types

### document
A scientific paper or other ingested source. Nodes represent the primary unit of evidence — a physical publication, uploaded PDF, or web document from which facts are extracted.

**Key properties:** `title`, `doi`, `authors`, `year`, `journal`, `abstract`, `source_type`, `general_domain`, `processing_status`

---

### fact
A single factual observation or claim extracted from a document by an ingestion agent. A fact is always grounded in a specific source document and may support or oppose one or more stylized facts.

**Key properties:** `content`, `document_id`, `entities`, `tags`, `confidence`, `status`

---

### stylized_fact
A general biological principle or pattern — a broad, theory-level statement that multiple specific facts can support or refute. Stylized facts form the conceptual backbone of the knowledge graph.

**Key properties:** `statement`, `category`, `sf_number`, `status`

---

### taxon
A taxonomic unit from the NCBI taxonomy tree (supplemented by GBIF data). Taxa form a strict parent-child hierarchy from root down to species level. The `rank` field determines the node's role in the hierarchy (kingdom, phylum, class, order, family, genus, species, etc.).

**Key properties:** `tax_id`, `name`, `rank`, `parent_tax_id`, `lineage`, `gbif_id`, `common_names`, `synonyms`

---

### chunk
A sub-document text segment produced during ingestion. Chunks are fixed-size windows over a document's content and carry vector embeddings for semantic search.

**Key properties:** `chunk_id`, `document_id`, `chunk_index`, `text`, `char_start`, `char_end`, `embedded`

---

## Edge Types

### extracted_from
Connects a **fact** to the **document** it was extracted from. Represents direct provenance.

`fact → document`

---

### supports / opposes
Connects a **fact** to a **stylized_fact** it provides evidence for or against. Carries a `confidence` score and a `status` field.

`fact → stylized_fact`

---

### is_child_of
Connects a **taxon** to its parent **taxon** in the NCBI taxonomy tree.

`taxon → taxon (parent)`

---

### studies
Connects a **document** to a **taxon** that the document is about or that appears prominently in it. Determined by the knowledge-graph agent with associated `confidence`, `evidence`, and `status`.

`document → taxon`

---

### cites
Connects a **document** to another **document** it cites. Represents the citation network.

`document → document`

---

### regulates
Connects a **stylized_fact** to another **stylized_fact** that it regulates or modulates.

`stylized_fact → stylized_fact`

---

### depends_on
Connects a **stylized_fact** to another **stylized_fact** it depends on logically or mechanistically.

`stylized_fact → stylized_fact`

---

### exhibited_by
Connects a **stylized_fact** to a **taxon** that exhibits or exemplifies the pattern described by the stylized fact.

`stylized_fact → taxon`

---

### has_chunk
Connects a **chunk** to the **document** it belongs to. Represents textual containment.

`chunk → document`

---

## Named Graphs

### citation_graph
The citation network between documents. Useful for bibliometric analysis and tracing intellectual lineage.

- **Nodes:** `documents`
- **Edges:** `cites` (document → document)

**Edge-building strategy — two phases:**

1. **DOI-based (bibliographic):** Citation edges are built from the `references` field on each document (a list of DOI strings). This requires the ingestion pipeline to populate `doc['references']`. Edges carry `properties.method = "doi"`.

2. **Taxon-overlap fallback (similarity-based):** If fewer than 10 DOI-based edges are produced (e.g. because `references` is not yet populated), a fallback builds `cites` edges between documents that study overlapping organisms. Similarity is Jaccard overlap of their taxon sets derived from `document_taxon_relations`. Only pairs with Jaccard ≥ 0.2 and within each document's top-5 most similar peers are included. These edges carry `properties.method = "taxon_overlap"` to distinguish them from real bibliographic citations — they represent shared research subject matter, not actual citation relationships.

---

### support_graph
The evidence network linking facts to the stylized facts they support or oppose, with documents as provenance roots.

- **Nodes:** `facts`, `stylized_facts`, `documents`
- **Edges:** `sf_support` (supports / opposes), `extracted_from`

---

### taxonomy_graph
The full NCBI taxonomic hierarchy. A tree where each node is a taxon and each edge points to the parent taxon.

- **Nodes:** `taxa`
- **Edges:** `taxonomical` (is_child_of)

---

### knowledge_graph
The full integrated knowledge graph — all domain knowledge in one materialized schema. Combines the taxonomy backbone, stylized facts, extracted facts, and documents with every evidence and relational edge type.

**Node types:**
- `stylized_fact` — from `stylized_facts` collection. `cluster_id = "sf:<category>"` (or `"sf:uncategorized"`)
- `fact` — from `facts` collection. `cluster_id = "fact"` (all facts share one cluster, colored by their SF later)
- `document` — from `documents` collection (only those linked to taxa in the fetched subtree). `cluster_id = "doc:<general_domain>"` (or `"doc:unknown"`)
- taxon nodes typed by rank — from `taxonomy_nodes`; `node_type` is set to the taxon's `rank` field (e.g. `species`, `genus`, `family`). `cluster_id = "taxon:<rank>"` (e.g. `"taxon:species"`)

Every node carries a `properties.cluster_id` for frontend cluster-based coloring.

**Edge types:**
- `extracted_from` — fact → document (via `fact.document_id`)
- `supports` / `opposes` — fact → stylized_fact (via `fact_sf_relations`)
- `is_child_of` — taxon → taxon parent (phylogenetic tree backbone)
- `studies` — document → taxon (via `document_taxon_relations`, confirmed/suggested status)
- `cites` — document → document (from `doc.references` list of DOIs, when populated)
- `regulates` — stylized_fact → stylized_fact (via `sf_sf_relations` collection, if it exists)
- `depends_on` — stylized_fact → stylized_fact (via `sf_sf_relations` collection, if it exists)
- `exhibited_by` — stylized_fact → taxon (via `sf_taxon_relations` collection, if it exists)

---

### chunk_graph
Relates text chunks to their parent documents. Used for retrieval-augmented generation (RAG) and semantic search workflows.

- **Nodes:** `chunks`, `documents`
- **Edges:** `chunk_belongs_to` (has_chunk)

---

### physiological_process (materialized schema)
Captures inter-stylized-fact relationships (regulatory, dependency) and their connection to taxa. Describes the causal and structural web of biological principles.

- **Nodes:** `stylized_facts`, `taxa`
- **Edges:** `regulates`, `depends_on`, `exhibited_by`
