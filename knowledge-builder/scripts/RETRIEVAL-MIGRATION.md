# Retrieval quality: production migration

Three independent steps, each gated on the one before. Every command that
writes to production checks for a recent backup itself and refuses without
one; the backup commands are listed where they are needed.
`advandeb_kb.backup_guard` must be on main (data-protection branch) first.

```bash
cd /home/adeb/dev/advandeb && set -a && . app/backend/.env && set +a
PY=~/miniforge3/envs/advandeb/bin/python
```

## 1. Deploy the code (no data change)

After this branch is merged and pulled:

```bash
sudo systemctl restart advandeb.target    # app backend + agent stack
```

Effects: chunker fix (new ingestions only), fact extraction sends `num_ctx`,
reranking off by default (`CHAT_USE_RERANKING`), passage-level fusion,
`semantic_search` is vector-only. The retrieval agent logs one warning — view
not found, MongoDB fallback — until step 2.

## 2. BM25 view on `chunks` (additive: one analyzer, one view)

Measured on a scratch copy: 129 s to build, +1.0 GB arangod RSS during the
build, 371 MB on disk. Built in the background (`inBackground`), so
`chunks` stays writable.

```bash
$PY scripts/backup/advandeb_backup.py --profile daily --only arango:advandeb_kb
$PY knowledge-builder/scripts/setup_chunks_search_view.py                           # dry run
$PY knowledge-builder/scripts/setup_chunks_search_view.py --production --apply --wait
```

The retrieval agent picks the view up within 10 minutes (or restart the agent
stack). Undo: drop view `chunks_text_search`. The analyzer `advandeb_text_en`
is shared with the facts / stylized-facts views (`setup_facts_search_views.py`);
drop it only once no view uses it (ArangoDB refuses while one does).

## 3. Corpus repair (`repair_corpus.py`)

Pause ingestion for the duration (batch PDF ingestion,
`embed_reproduction_abstracts.py`): they write the live vector store, and the
swap refuses if it changed.

```bash
R="$PY knowledge-builder/scripts/repair_corpus.py --device cuda:0"
$R plan                                                   # read-only

$PY scripts/backup/advandeb_backup.py --profile daily --only arango:advandeb_kb
$R rechunk-library --apply --production                   # ~255k chunks, minutes
$R chunk-abstracts --apply --production                   # OPTIONAL: 3.28M abstracts, ~12.1M chunks, ~20 min
$R build-store --apply                                    # new store at data/chromadb.repair-work
$R verify
```

`build-store` writes only the new directory; the live store is untouched and
the agents keep serving from it. Duration at the measured ~450 vectors/s:

| scope | vectors | build | disk | HNSW RAM per process |
|---|---|---|---|---|
| without `chunk-abstracts` | 2.47M | ~1.5 h | ~15 GB | ~5 GB |
| with `chunk-abstracts` | 14.6M | ~9-12 h | ~90 GB | ~29 GB |

Both the retrieval agent and the app backend hold the store in RAM.

Maintenance window (minutes):

```bash
$PY scripts/backup/advandeb_backup.py --profile weekly --only chroma
$PY scripts/backup/advandeb_backup.py --profile daily --only arango:advandeb_kb
sudo systemctl stop advandeb.target
$R swap --apply --production         # checks no process holds either store, live unchanged since build-store
sudo systemctl start advandeb.target
$R retire-duplicates-arango --apply --production   # ~601k duplicate-lineage chunks + edges
```

Rollback:

* vectors (services stopped): `mv data/chromadb data/chromadb.repair-work && mv data/chromadb.pre-<run id> data/chromadb`
  (the run id is in `data/repair-state/run_id`);
* Arango: everything written carries `repair_run: <run id>`; the library
  documents' old chunks were replaced, so restore `chunks` and
  `chunk_belongs_to` from the backup taken before `rechunk-library`.

Afterwards: the FULLTEXT index on `chunks.text` (1.09 GB, ~5 GB after
`chunk-abstracts`) has no user any more and can be dropped.
