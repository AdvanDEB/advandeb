# Retrieval evaluation

`scripts/eval_retrieval.py` measures hybrid retrieval offline: recall@k and MRR
against judged evidence, on a copy of the vector store and a scratch ArangoDB.
It never needs the live ChromaDB store (it refuses to open it) and only reads
production ArangoDB/MongoDB.

## Query set

`sf_support_queries.json` is built by `eval_retrieval.py build-queries` from
`analysis/sf_support_fullcorpus/raw/*.json`: one query per stylized fact (the SF
statement), and a paper is relevant when **both** judges (gpt-oss:120b and
Claude) labelled one of its passages as supporting or contradicting the SF.
60 queries; 300 (deb) + 201 (reproduction) relevant papers, 320 distinct.

Relevance is judged per paper, because the passages came from a differently
chunked corpus. Every chunk lineage of a paper maps to one key
(`file:<pdf basename>` or `oa:<OpenAlex id>`).

Caveats:

* Pooled relevance: the judged passages were themselves found by retrieval
  (nomic-embed, top hits per SF), so unlabelled papers may be relevant. Read the
  numbers as comparisons between configurations.
* Only 192 of the 320 relevant papers have any chunk in the corpus. On the
  reproduction side, 59 of 187: the rest are among the ~3.28M abstracts that
  were never chunked or embedded. The few that are retrievable sit at ranks
  14-1800 in a 2.2M-chunk pool where a handful of labels per SF cannot
  measure top-20 ranking, so **the deb slice (59 queries) is the measure**;
  reproduction numbers are reported for coverage only.

## Commands

```bash
cd /home/adeb/dev/advandeb && set -a && . app/backend/.env && set +a
PY=~/miniforge3/envs/advandeb/bin/python
cd knowledge-builder

# a copy of the vector store (never the live directory)
mkdir -p /tmp/chroma_copy
ionice -c3 cp -a ../data/chromadb/chroma.sqlite3 ../data/chromadb/<segment-uuid> /tmp/chroma_copy/

# chunks + BM25 view in a scratch database
arangorestore --server.database advandeb_kb_retrieval_scratch --create-database true \
    --collection chunks --input-directory ~/backups/advandeb/<run>/arango/advandeb_kb ...
$PY scripts/setup_chunks_search_view.py --db advandeb_kb_retrieval_scratch --apply --wait

$PY scripts/eval_retrieval.py run --chroma-dir /tmp/chroma_copy \
    --arango-db advandeb_kb_retrieval_scratch --rerank-model gemma3:latest --out report.json
$PY scripts/eval_retrieval.py chunker-ab --device cuda:0
```

`run` compares, per query, on the same vector and keyword hits:

| config | what |
|---|---|
| before (vec+mongo) | the deployed code (`--old-rev main`): vector + MongoDB `$text` over the frozen legacy `chunks`, RRF by chunk id |
| vec+bm25, old fusion | BM25 over the Arango view, old fusion — isolates the keyword-arm switch |
| vector only / bm25 only | one arm, repeated passages dropped |
| after (vec+bm25) | this branch: BM25 view + passage-level fusion |
| after + rerank | plus the LLM reranker |

## Results (2026-10-28, deb slice, 59 queries, top 20)

| config | R@5 | R@10 | R@20 | MRR | duplicate passages in top 10 |
|---|---|---|---|---|---|
| before (vec+mongo) | 0.385 | 0.452 | 0.565 | 0.694 | 1.83 |
| vec+bm25, old fusion | 0.373 | 0.458 | 0.570 | 0.715 | 2.64 |
| vector only | 0.397 | 0.494 | 0.608 | 0.685 | 0.09 |
| bm25 only | 0.374 | 0.456 | 0.538 | 0.727 | 0.17 |
| **after (vec+bm25)** | **0.416** | **0.508** | **0.640** | 0.715 | **0.12** |
| after + rerank (gemma3) | 0.411 | 0.508 | 0.640 | 0.738 | 0.12 |

Paired differences (mean, 95% bootstrap CI, queries won/lost):

* after vs before: R@10 **+0.055 [+0.023, +0.095]** 16/3; R@5 +0.031 [−0.013, +0.080];
  MRR +0.022 [−0.043, +0.086].
* Passage-level fusion (after vs old fusion): R@5 **+0.042 [+0.016, +0.074]** 10/0,
  R@10 **+0.050 [+0.029, +0.074]** 16/0, MRR ±0. The same PDF is in the store under
  two (vector) or three (Arango) chunk-id lineages, chunked identically; keyed
  by id, copies took 1.8 of the top 10 slots before (2.6 once BM25 also returns
  the Arango lineage), and a passage both arms found was not fused.
* Keyword arm switch alone (old fusion, Mongo → BM25): R@10 +0.005 [−0.024, +0.037]
  on the deb slice — Mongo's legacy collection holds the same library, so this
  slice cannot show the gain; what changes is that the keyword arm now covers
  the 2.2M abstract chunks too, and its median latency drops from 383 ms to 32 ms.
* Reranking (after + rerank vs after): MRR +0.023 [−0.061, +0.108], R@5 −0.005,
  at +1.26 s median per search. Not significant, so `CHAT_USE_RERANKING`
  defaults to false; `RERANK_MODEL` defaults to the installed `gemma3:latest`.

Median latency per arm: vector 192 ms (copy, cold disk cache), BM25 32 ms,
Mongo `$text` 383 ms, rerank 1,258 ms.

### Chunker (old vs fixed), full-text library only

`chunker-ab` re-chunks the 1,218 library documents (116.7M chars) with both
chunkers, embeds both (all-MiniLM-L6-v2), and runs vector search over each.

| chunker | chunks | chunks with a 100-char run without spaces | R@5 | R@10 | R@20 | MRR |
|---|---|---|---|---|---|---|
| old | 250,585 | 5,089 | 0.469 | 0.577 | 0.688 | 0.703 |
| fixed | 254,806 | 270 | 0.459 | 0.614 | 0.693 | 0.725 |

Paired (fixed vs old): R@10 +0.038 [−0.004, +0.084] 15/9, MRR +0.021 [−0.062, +0.108],
R@5 −0.010 [−0.057, +0.039]. The direction favours the fix but 59 queries do not
resolve it; what is unambiguous is the text: 19× fewer chunks with glued words.

The remaining 270 runs are in the extracted PDF text itself ("occursduring"
is in `documents.content`), not made by the chunker.

## Store health findings (on the copy)

* ~32% of the `doc_<hash>` lineage (~86k of 269,275 vectors) is in
  `chroma.sqlite3` but missing from the HNSW index: never returned by vector
  search; `get(..., include=["embeddings"])` and any metadata-filtered query that
  touches them fail with "Error finding id". The ObjectId and OpenAlex lineages
  are intact (0 of 10,000 sampled).
* A `where` filter on `general_domain` takes 1.5-15 s (unfiltered: ~10 ms);
  `$ne` fails outright. Domain filtering is therefore done on an over-fetched
  unfiltered query.
* `general_domain` is `"reproduction"` on 2.2M vectors, `""` on 343k and absent
  on 269k: the domain filter only works as `deb` = "not reproduction".

## Vector store build throughput (`scripts/repair_corpus.py build-store`)

Fresh ChromaDB 1.5.5 store, 5,000-vector upserts: ~520/s falling to ~420/s by
200k vectors (cumulative 469/s), with documents stored. Without documents the
same upserts run at ~1,100/s — the documents' full-text index is most of the
cost — but the retrieval code reads chunk text from Chroma, so the build keeps
them. all-MiniLM-L6-v2 embeds ~1,000 chunks/s on one (shared) Quadro RTX 8000;
build-store overlaps embedding with upserts, so Chroma is the bound.

## ArangoSearch view (`scripts/setup_chunks_search_view.py`)

Measured on the scratch copy of `chunks` (3,077,659 documents, Arango 3.12.8):
build 129 s, link index 371 MB on disk (the unused FULLTEXT index on
`chunks.text` is 1.09 GB), arangod RSS +1.0 GB during the build. Built with
`inBackground: true`, so the collection stays writable.
