#!/usr/bin/env python3
"""
Full migration: MongoDB advandeb_knowledge_builder_kb → ArangoDB advandeb_kb.

Steps performed (in order):
  1. Wipe all vertex and edge collections in ArangoDB (keep graph definitions)
  2. Migrate taxonomy_nodes  → taxa
  3. Migrate taxonomy edges  → taxonomical  (parent_tax_id links)
  4. Migrate stylized_facts  → stylized_facts
  5. Migrate documents       → documents
  6. Migrate facts           → facts
  7. Migrate chunks          → chunks  (text only — embeddings stay in ChromaDB)
  8. Build chunk_belongs_to  → chunk_belongs_to  (chunk → document edges)
  9. Build sf_support edges  → sf_support  (from fact_sf_relations)
 10. Build citations edges   → citations   (from document.references DOI cross-links)

Collections intentionally skipped (stay in MongoDB):
  ingestion_batches, ingestion_jobs  — workflow state, not KB data
  agent_memory, chat_messages, chat_sessions — app data (already on app MongoDB)
  graph_nodes, graph_edges, graph_schemas  — materialized cache, replaced by live queries
  document_taxon_relations — empty

Run from repo root:
  PYTHONPATH=app/backend:knowledge-builder \
    miniforge3/envs/advandeb/bin/python knowledge-builder/scripts/migrate_mongo_to_arango.py
"""
import sys
import os
import logging
from datetime import datetime, timezone
from pathlib import Path

# Allow running from the knowledge-builder/scripts directory too
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "knowledge-builder"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("migration")

BATCH_SIZE = 2000          # documents per ArangoDB import batch
TAXA_BATCH_SIZE = 5000     # larger batch for taxa (simple structure)

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_mongo_kb():
    from pymongo import MongoClient
    uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    client = MongoClient(uri)
    return client["advandeb_knowledge_builder_kb"]


def get_arango_db():
    from arango import ArangoClient
    url  = os.environ.get("ARANGO_URL",      "http://localhost:8529")
    name = os.environ.get("ARANGO_DB_NAME",  "advandeb_kb")
    user = os.environ.get("ARANGO_USERNAME", "root")
    pwd  = os.environ.get("ARANGO_PASSWORD", "sparusaurata")
    client = ArangoClient(hosts=url)
    return client.db(name, username=user, password=pwd)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt_to_str(v):
    """Convert datetime → ISO string, pass strings through, None → None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _sanitize(v):
    """Recursively convert any MongoDB-specific types to JSON-safe equivalents."""
    from bson import ObjectId
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _sanitize(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_sanitize(item) for item in v]
    return v


def _bulk_insert(col, docs, overwrite=True):
    """Insert a batch into an ArangoDB collection.  Returns (inserted, errors)."""
    if not docs:
        return 0, 0
    result = col.import_bulk(docs, on_duplicate="replace" if overwrite else "error",
                             halt_on_error=False)
    created  = result.get("created", 0)
    replaced = result.get("replaced", 0)
    errors   = result.get("errors", 0)
    return created + replaced, errors


# ---------------------------------------------------------------------------
# Step 1 — wipe ArangoDB collections
# ---------------------------------------------------------------------------

def step_wipe(adb):
    log.info("=== Step 1: Wiping ArangoDB collections ===")
    vertex_cols = ["documents", "facts", "stylized_facts", "taxa", "chunks", "provenance_traces"]
    edge_cols   = ["sf_support", "citations", "knowledge_graph", "chunk_belongs_to", "taxonomical"]

    for name in vertex_cols + edge_cols:
        try:
            col = adb.collection(name)
            col.truncate()
            log.info("  truncated %-20s", name)
        except Exception as exc:
            log.warning("  could not truncate %s: %s", name, exc)

    log.info("  done — all collections empty")


# ---------------------------------------------------------------------------
# Step 2 — migrate taxa
# ---------------------------------------------------------------------------

def step_taxa(mongo_kb, adb):
    log.info("=== Step 2: Migrating taxa ===")
    col = adb.collection("taxa")
    total = mongo_kb.taxonomy_nodes.count_documents({})
    log.info("  source: %d taxonomy_nodes", total)

    inserted = errors = 0
    batch = []

    cursor = mongo_kb.taxonomy_nodes.find({})
    for node in cursor:
        tax_id = node.get("tax_id")
        if tax_id is None:
            continue
        doc = {
            "_key":           str(tax_id),
            "tax_id":         tax_id,
            "name":           node.get("name"),
            "rank":           node.get("rank"),
            "parent_tax_id":  node.get("parent_tax_id"),
            "lineage":        node.get("lineage", []),
            "common_names":   node.get("common_names", []),
            "synonyms":       node.get("synonyms", []),
            "gbif_usage_key": node.get("gbif_usage_key"),
            "ncbi_sourced":   node.get("ncbi_sourced", False),
            "created_at":     _dt_to_str(node.get("created_at")),
            "updated_at":     _dt_to_str(node.get("updated_at")),
        }
        batch.append(doc)
        if len(batch) >= TAXA_BATCH_SIZE:
            ok, err = _bulk_insert(col, batch)
            inserted += ok; errors += err
            batch = []
            if (inserted + errors) % 100000 == 0:
                log.info("    taxa progress: %d / %d", inserted + errors, total)

    if batch:
        ok, err = _bulk_insert(col, batch)
        inserted += ok; errors += err

    log.info("  taxa done: inserted=%d errors=%d", inserted, errors)
    return inserted


# ---------------------------------------------------------------------------
# Step 3 — build taxonomical (parent-child) edges
# ---------------------------------------------------------------------------

def step_taxonomical(mongo_kb, adb):
    log.info("=== Step 3: Building taxonomical edges ===")
    col = adb.collection("taxonomical")
    total = mongo_kb.taxonomy_nodes.count_documents({"parent_tax_id": {"$exists": True, "$ne": None}})
    log.info("  source: %d nodes with parent_tax_id", total)

    inserted = errors = 0
    batch = []

    cursor = mongo_kb.taxonomy_nodes.find(
        {"parent_tax_id": {"$exists": True, "$ne": None}},
        {"tax_id": 1, "parent_tax_id": 1},
    )
    for node in cursor:
        child  = node.get("tax_id")
        parent = node.get("parent_tax_id")
        if child is None or parent is None:
            continue
        doc = {
            "_key":  f"{child}_to_{parent}",
            "_from": f"taxa/{child}",
            "_to":   f"taxa/{parent}",
            "edge_type": "is_child_of",
        }
        batch.append(doc)
        if len(batch) >= TAXA_BATCH_SIZE:
            ok, err = _bulk_insert(col, batch)
            inserted += ok; errors += err
            batch = []
            if (inserted + errors) % 200000 == 0:
                log.info("    taxonomical edges progress: %d", inserted + errors)

    if batch:
        ok, err = _bulk_insert(col, batch)
        inserted += ok; errors += err

    log.info("  taxonomical edges done: inserted=%d errors=%d", inserted, errors)
    return inserted


# ---------------------------------------------------------------------------
# Step 4 — migrate stylized_facts
# ---------------------------------------------------------------------------

def step_stylized_facts(mongo_kb, adb):
    log.info("=== Step 4: Migrating stylized_facts ===")
    col = adb.collection("stylized_facts")
    total = mongo_kb.stylized_facts.count_documents({})
    log.info("  source: %d stylized_facts", total)

    inserted = errors = 0
    batch = []

    for sf in mongo_kb.stylized_facts.find({}):
        doc = {
            "_key":       str(sf["_id"]),
            "statement":  sf.get("statement"),
            "sf_number":  sf.get("sf_number"),
            "category":   sf.get("category"),
            "status":     sf.get("status", "published"),
            "created_at": _dt_to_str(sf.get("created_at")),
            "updated_at": _dt_to_str(sf.get("updated_at")),
        }
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            ok, err = _bulk_insert(col, batch)
            inserted += ok; errors += err
            batch = []

    if batch:
        ok, err = _bulk_insert(col, batch)
        inserted += ok; errors += err

    log.info("  stylized_facts done: inserted=%d errors=%d", inserted, errors)
    return inserted


# ---------------------------------------------------------------------------
# Step 5 — migrate documents
# ---------------------------------------------------------------------------

def step_documents(mongo_kb, adb):
    log.info("=== Step 5: Migrating documents ===")
    col = adb.collection("documents")
    total = mongo_kb.documents.count_documents({})
    log.info("  source: %d documents", total)

    # Deduplicate by DOI — keep the most recently updated version of each DOI.
    # Documents with no DOI (doi=None/"") are always kept.
    seen_dois: dict = {}   # doi -> doc dict
    no_doi_docs: list = []

    for mdoc in mongo_kb.documents.find({}):
        doi = (mdoc.get("doi") or "").strip().lower()
        doc = {
            "_key":              str(mdoc["_id"]),
            "title":             mdoc.get("title"),
            "doi":               mdoc.get("doi"),
            "authors":           _sanitize(mdoc.get("authors", [])),
            "year":              mdoc.get("year"),
            "journal":           mdoc.get("journal"),
            "volume":            mdoc.get("volume"),
            "issue":             mdoc.get("issue"),
            "pages":             mdoc.get("pages"),
            "references":        _sanitize(mdoc.get("references", [])),
            "keywords":          _sanitize(mdoc.get("keywords", [])),
            "openalex_id":       mdoc.get("openalex_id"),
            "pmid":              mdoc.get("pmid"),
            "cited_by_count":    mdoc.get("cited_by_count"),
            "is_retracted":      mdoc.get("is_retracted", False),
            "source_type":       mdoc.get("source_type"),
            "source_path":       mdoc.get("source_path"),
            "general_domain":    mdoc.get("general_domain"),
            "processing_status": mdoc.get("processing_status", "completed"),
            "embedding_status":  mdoc.get("embedding_status"),
            "num_chunks":        mdoc.get("num_chunks"),
            "num_facts":         mdoc.get("num_facts", 0),
            "content":           mdoc.get("content"),
            "abstract":          mdoc.get("abstract"),
            "created_at":        _dt_to_str(mdoc.get("created_at")),
            "updated_at":        _dt_to_str(mdoc.get("updated_at")),
        }
        if not doi:
            no_doi_docs.append(doc)
        else:
            existing = seen_dois.get(doi)
            if existing is None:
                seen_dois[doi] = doc
            else:
                # Keep whichever was updated more recently
                existing_ts = existing.get("updated_at") or ""
                new_ts      = doc.get("updated_at") or ""
                if new_ts > existing_ts:
                    seen_dois[doi] = doc

    deduped = list(seen_dois.values()) + no_doi_docs
    skipped = total - len(deduped)
    log.info("  deduplicated: %d unique docs (%d duplicates by DOI removed)", len(deduped), skipped)

    inserted = errors = 0
    batch = []
    for doc in deduped:
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            ok, err = _bulk_insert(col, batch)
            inserted += ok; errors += err
            batch = []
    if batch:
        ok, err = _bulk_insert(col, batch)
        inserted += ok; errors += err

    log.info("  documents done: inserted=%d errors=%d", inserted, errors)
    return inserted


# ---------------------------------------------------------------------------
# Step 6 — migrate facts
# ---------------------------------------------------------------------------

def step_facts(mongo_kb, adb):
    log.info("=== Step 6: Migrating facts ===")
    col = adb.collection("facts")
    total = mongo_kb.facts.count_documents({})
    log.info("  source: %d facts", total)

    inserted = errors = 0
    batch = []

    for mfact in mongo_kb.facts.find({}):
        doc_id = mfact.get("document_id")
        doc = {
            "_key":               str(mfact["_id"]),
            "content":            mfact.get("content"),
            "document_id":        str(doc_id) if doc_id else None,
            "content_fingerprint":mfact.get("content_fingerprint"),
            "page_number":        mfact.get("page_number"),
            "entities":           _sanitize(mfact.get("entities", [])),
            "tags":               mfact.get("tags", []),
            "general_domain":     mfact.get("general_domain"),
            "confidence":         mfact.get("confidence", 0.8),
            "status":             mfact.get("status", "pending"),
            "additional_sources": _sanitize(mfact.get("additional_sources", [])),
            "created_at":         _dt_to_str(mfact.get("created_at")),
            "updated_at":         _dt_to_str(mfact.get("updated_at")),
        }
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            ok, err = _bulk_insert(col, batch)
            inserted += ok; errors += err
            batch = []
            if (inserted + errors) % 20000 == 0:
                log.info("    facts progress: %d / %d", inserted + errors, total)

    if batch:
        ok, err = _bulk_insert(col, batch)
        inserted += ok; errors += err

    log.info("  facts done: inserted=%d errors=%d", inserted, errors)
    return inserted


# ---------------------------------------------------------------------------
# Step 7 — migrate chunks (text only)
# ---------------------------------------------------------------------------

def step_chunks(mongo_kb, adb):
    log.info("=== Step 7: Migrating chunks (text only) ===")
    col = adb.collection("chunks")
    total = mongo_kb.chunks.count_documents({})
    log.info("  source: %d chunks", total)

    inserted = errors = 0
    batch = []

    for mc in mongo_kb.chunks.find({}, {"embedding": 0}):
        doc_id = mc.get("document_id")
        chunk_id = mc.get("chunk_id", str(mc["_id"]))
        doc = {
            "_key":        chunk_id,
            "chunk_id":    chunk_id,
            "document_id": str(doc_id) if doc_id else None,
            "chunk_index": mc.get("chunk_index"),
            "text":        mc.get("text"),
            "char_start":  mc.get("char_start"),
            "char_end":    mc.get("char_end"),
            "source_path": mc.get("source_path"),
            "embedded":    mc.get("embedded", mc.get("embedding_status") == "embedded"),
            "created_at":  _dt_to_str(mc.get("created_at")),
        }
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            ok, err = _bulk_insert(col, batch)
            inserted += ok; errors += err
            batch = []
            if (inserted + errors) % 50000 == 0:
                log.info("    chunks progress: %d / %d", inserted + errors, total)

    if batch:
        ok, err = _bulk_insert(col, batch)
        inserted += ok; errors += err

    log.info("  chunks done: inserted=%d errors=%d", inserted, errors)
    return inserted


# ---------------------------------------------------------------------------
# Step 8 — build chunk_belongs_to edges
# ---------------------------------------------------------------------------

def step_chunk_belongs_to(adb):
    log.info("=== Step 8: Building chunk_belongs_to edges ===")
    col = adb.collection("chunk_belongs_to")
    chunks_col = adb.collection("chunks")
    total = chunks_col.count()
    log.info("  source: %d chunks", total)

    inserted = errors = 0
    batch = []

    cursor = adb.aql.execute(
        "FOR c IN chunks FILTER c.document_id != null RETURN {chunk_id: c.chunk_id, document_id: c.document_id}",
        batch_size=5000,
    )
    for c in cursor:
        doc = {
            "_key":  f"{c['chunk_id']}_belongs",
            "_from": f"chunks/{c['chunk_id']}",
            "_to":   f"documents/{c['document_id']}",
            "edge_type": "belongs_to",
        }
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            ok, err = _bulk_insert(col, batch)
            inserted += ok; errors += err
            batch = []
            if (inserted + errors) % 50000 == 0:
                log.info("    chunk_belongs_to progress: %d", inserted + errors)

    if batch:
        ok, err = _bulk_insert(col, batch)
        inserted += ok; errors += err

    log.info("  chunk_belongs_to done: inserted=%d errors=%d", inserted, errors)
    return inserted


# ---------------------------------------------------------------------------
# Step 9 — build sf_support edges from fact_sf_relations
# ---------------------------------------------------------------------------

def step_sf_support(mongo_kb, adb):
    log.info("=== Step 9: Building sf_support edges ===")
    col = adb.collection("sf_support")
    total = mongo_kb.fact_sf_relations.count_documents({})
    log.info("  source: %d fact_sf_relations", total)

    inserted = errors = 0
    batch = []

    for rel in mongo_kb.fact_sf_relations.find({}):
        fact_id = rel.get("fact_id")
        sf_id   = rel.get("sf_id")
        if not fact_id or not sf_id:
            continue
        fact_key = str(fact_id)
        sf_key   = str(sf_id)
        edge_key = f"{fact_key}_{sf_key}"
        doc = {
            "_key":         edge_key,
            "_from":        f"facts/{fact_key}",
            "_to":          f"stylized_facts/{sf_key}",
            "relation_type":rel.get("relation_type", "supports"),
            "confidence":   rel.get("confidence", 0.9),
            "status":       rel.get("status", "suggested"),
            "created_by":   rel.get("created_by", "agent"),
            "created_at":   _dt_to_str(rel.get("created_at")),
            "updated_at":   _dt_to_str(rel.get("updated_at")),
        }
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            ok, err = _bulk_insert(col, batch)
            inserted += ok; errors += err
            batch = []

    if batch:
        ok, err = _bulk_insert(col, batch)
        inserted += ok; errors += err

    log.info("  sf_support done: inserted=%d errors=%d", inserted, errors)
    return inserted


# ---------------------------------------------------------------------------
# Step 10 — build citations edges from document.references (DOI cross-links)
# ---------------------------------------------------------------------------

def step_citations(adb):
    log.info("=== Step 10: Building citations edges from DOI references ===")
    col = adb.collection("citations")

    # Build DOI → _key index from the documents we just inserted
    log.info("  building DOI index...")
    doi_to_key = {}
    cursor = adb.aql.execute(
        "FOR d IN documents FILTER d.doi != null AND d.doi != '' RETURN {doi: d.doi, _key: d._key}",
        batch_size=2000,
    )
    for d in cursor:
        doi_to_key[d["doi"].lower().strip()] = d["_key"]
    log.info("  DOI index: %d entries", len(doi_to_key))

    inserted = errors = skipped = 0
    batch = []

    cursor = adb.aql.execute(
        "FOR d IN documents FILTER LENGTH(d.references) > 0 RETURN {_key: d._key, refs: d.references}",
        batch_size=500,
    )
    for d in cursor:
        src_key = d["_key"]
        for ref_doi in d.get("refs", []):
            if not ref_doi:
                continue
            tgt_key = doi_to_key.get(ref_doi.lower().strip())
            if not tgt_key:
                skipped += 1
                continue
            if tgt_key == src_key:
                continue   # skip self-loops
            edge_key = f"{src_key}_{tgt_key}"
            doc = {
                "_key":      edge_key,
                "_from":     f"documents/{src_key}",
                "_to":       f"documents/{tgt_key}",
                "edge_type": "cites",
            }
            batch.append(doc)
            if len(batch) >= BATCH_SIZE:
                ok, err = _bulk_insert(col, batch)
                inserted += ok; errors += err
                batch = []

    if batch:
        ok, err = _bulk_insert(col, batch)
        inserted += ok; errors += err

    log.info("  citations done: inserted=%d errors=%d skipped(no DOI match)=%d",
             inserted, errors, skipped)
    return inserted


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify(mongo_kb, adb):
    log.info("=== Verification ===")
    checks = [
        ("taxa",            mongo_kb.taxonomy_nodes.count_documents({})),
        ("taxonomical",     mongo_kb.taxonomy_nodes.count_documents({"parent_tax_id": {"$exists": True, "$ne": None}})),
        ("stylized_facts",  mongo_kb.stylized_facts.count_documents({})),
        ("documents",       mongo_kb.documents.count_documents({}) - 52),   # ~52 DOI duplicates expected
        ("facts",           mongo_kb.facts.count_documents({})),
        ("chunks",          mongo_kb.chunks.count_documents({})),
        ("sf_support",      mongo_kb.fact_sf_relations.count_documents({})),
    ]
    all_ok = True
    for col_name, expected in checks:
        actual = adb.collection(col_name).count()
        ok = actual >= expected
        status = "OK" if ok else "MISMATCH"
        log.info("  %-22s  expected>=%d  actual=%d  %s", col_name, expected, actual, status)
        if not ok:
            all_ok = False

    # citations — just report count (no direct mongo source to compare)
    citations_count = adb.collection("citations").count()
    chunk_bt_count  = adb.collection("chunk_belongs_to").count()
    log.info("  %-22s  actual=%d", "citations",        citations_count)
    log.info("  %-22s  actual=%d", "chunk_belongs_to", chunk_bt_count)

    if all_ok:
        log.info("  All counts verified OK")
    else:
        log.warning("  Some counts did not match — check errors above")
    return all_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-from", default="wipe",
        choices=["wipe","taxa","taxonomical","stylized_facts","documents",
                 "facts","chunks","chunk_belongs_to","sf_support","citations","verify"],
        help="Skip earlier steps and resume from this step")
    args = parser.parse_args()
    rf = args.resume_from

    start = datetime.now()
    log.info("Migration started at %s (resume-from=%s)", start.strftime("%Y-%m-%d %H:%M:%S"), rf)

    mongo_kb = get_mongo_kb()
    adb      = get_arango_db()

    steps = ["wipe","taxa","taxonomical","stylized_facts","documents",
             "facts","chunks","chunk_belongs_to","sf_support","citations","verify"]
    run_from = steps.index(rf)

    if run_from <= steps.index("wipe"):             step_wipe(adb)
    if run_from <= steps.index("taxa"):             step_taxa(mongo_kb, adb)
    if run_from <= steps.index("taxonomical"):      step_taxonomical(mongo_kb, adb)
    if run_from <= steps.index("stylized_facts"):   step_stylized_facts(mongo_kb, adb)
    if run_from <= steps.index("documents"):        step_documents(mongo_kb, adb)
    if run_from <= steps.index("facts"):            step_facts(mongo_kb, adb)
    if run_from <= steps.index("chunks"):           step_chunks(mongo_kb, adb)
    if run_from <= steps.index("chunk_belongs_to"): step_chunk_belongs_to(adb)
    if run_from <= steps.index("sf_support"):       step_sf_support(mongo_kb, adb)
    if run_from <= steps.index("citations"):        step_citations(adb)
    verify(mongo_kb, adb)

    elapsed = (datetime.now() - start).total_seconds()
    log.info("Migration complete in %.1f seconds (%.1f minutes)", elapsed, elapsed / 60)


if __name__ == "__main__":
    main()
