#!/usr/bin/env python3
"""
Migration script: MongoDB → ArangoDB

Migrates existing advandeb_kb data from MongoDB to ArangoDB:
  - documents     → documents collection
  - facts         → facts collection + edge citations (document→fact, via knowledge_graph)
  - stylized_facts→ stylized_facts collection
  - fact_sf_relations → sf_support edge collection
  - taxonomy_nodes → taxa collection + taxonomical edge collection
  - document_taxon_relations → knowledge_graph edge collection

Usage:
    # Dry run (no writes):
    python scripts/migrate_mongo_to_arango.py --dry-run

    # Live migration:
    python scripts/migrate_mongo_to_arango.py

    # Specific collections only:
    python scripts/migrate_mongo_to_arango.py --collections documents facts

Environment (reads from dev-server/.env or env vars):
    MONGODB_URL, DATABASE_NAME
    ARANGO_URL, ARANGO_DB_NAME, ARANGO_USERNAME, ARANGO_PASSWORD
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Allow running from repo root without installing
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / "dev-server" / ".env")

from advandeb_kb.config.settings import settings
from advandeb_kb.database.arango_client import ArangoDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("migrate")

# ------------------------------------------------------------------
# MongoDB access (sync PyMongo)
# ------------------------------------------------------------------

def get_mongo_db():
    from pymongo import MongoClient
    client = MongoClient(settings.MONGODB_URL)
    return client[settings.DATABASE_NAME]


# ------------------------------------------------------------------
# Document ID → ArangoDB _key helper
# ------------------------------------------------------------------

def mongo_id_to_key(oid) -> str:
    """Convert a PyMongo ObjectId (or string) to an ArangoDB-safe _key."""
    return str(oid)


# ------------------------------------------------------------------
# Per-collection migrators
# ------------------------------------------------------------------

def migrate_documents(mongo_db, arango: ArangoDatabase, dry_run: bool) -> int:
    col = mongo_db["documents"]
    count = 0
    for doc in col.find():
        arango_doc = {
            "_key": mongo_id_to_key(doc["_id"]),
            "title": doc.get("title"),
            "doi": doc.get("doi"),
            "authors": doc.get("authors", []),
            "year": doc.get("year"),
            "journal": doc.get("journal"),
            "abstract": doc.get("abstract"),
            "content": doc.get("content"),
            "source_type": doc.get("source_type", "manual"),
            "source_path": doc.get("source_path"),
            "general_domain": doc.get("general_domain"),
            "processing_status": doc.get("processing_status", "pending"),
            "created_at": str(doc.get("created_at", "")),
            "updated_at": str(doc.get("updated_at", "")),
        }
        if not dry_run:
            arango.upsert("documents", arango_doc)
        count += 1
    logger.info("[documents] %s %d records", "DRY" if dry_run else "migrated", count)
    return count


def migrate_facts(mongo_db, arango: ArangoDatabase, dry_run: bool) -> int:
    col = mongo_db["facts"]
    count = 0
    for doc in col.find():
        fact_key = mongo_id_to_key(doc["_id"])
        arango_doc = {
            "_key": fact_key,
            "content": doc.get("content", ""),
            "document_id": mongo_id_to_key(doc.get("document_id", "")),
            "page_number": doc.get("page_number"),
            "entities": doc.get("entities", []),
            "tags": doc.get("tags", []),
            "general_domain": doc.get("general_domain"),
            "confidence": doc.get("confidence", 0.8),
            "status": doc.get("status", "pending"),
            "created_at": str(doc.get("created_at", "")),
            "updated_at": str(doc.get("updated_at", "")),
        }
        if not dry_run:
            arango.upsert("facts", arango_doc)
        count += 1
    logger.info("[facts] %s %d records", "DRY" if dry_run else "migrated", count)
    return count


def migrate_stylized_facts(mongo_db, arango: ArangoDatabase, dry_run: bool) -> int:
    col = mongo_db["stylized_facts"]
    count = 0
    for doc in col.find():
        arango_doc = {
            "_key": mongo_id_to_key(doc["_id"]),
            "statement": doc.get("statement", ""),
            "category": doc.get("category", ""),
            "sf_number": doc.get("sf_number"),
            "status": doc.get("status", "pending"),
            "created_at": str(doc.get("created_at", "")),
            "updated_at": str(doc.get("updated_at", "")),
        }
        if not dry_run:
            arango.upsert("stylized_facts", arango_doc)
        count += 1
    logger.info("[stylized_facts] %s %d records", "DRY" if dry_run else "migrated", count)
    return count


def migrate_fact_sf_relations(mongo_db, arango: ArangoDatabase, dry_run: bool) -> int:
    col = mongo_db["fact_sf_relations"]
    count = 0
    for doc in col.find():
        fact_key = mongo_id_to_key(doc.get("fact_id", ""))
        sf_key = mongo_id_to_key(doc.get("sf_id", ""))
        edge = {
            "_key": mongo_id_to_key(doc["_id"]),
            "_from": f"facts/{fact_key}",
            "_to": f"stylized_facts/{sf_key}",
            "relation_type": doc.get("relation_type", "supports"),
            "confidence": doc.get("confidence", 0.5),
            "status": doc.get("status", "suggested"),
            "created_by": doc.get("created_by", "agent"),
            "created_at": str(doc.get("created_at", "")),
        }
        if not dry_run:
            arango.upsert("sf_support", edge)
        count += 1
    logger.info("[sf_support edges] %s %d records", "DRY" if dry_run else "migrated", count)
    return count


def migrate_taxonomy(mongo_db, arango: ArangoDatabase, dry_run: bool) -> int:
    col = mongo_db["taxonomy_nodes"]
    count_vertices = 0
    count_edges = 0

    for doc in col.find():
        key = str(doc.get("tax_id", mongo_id_to_key(doc["_id"])))
        arango_doc = {
            "_key": key,
            "tax_id": doc.get("tax_id"),
            "name": doc.get("name", ""),
            "rank": doc.get("rank", ""),
            "parent_tax_id": doc.get("parent_tax_id"),
            "lineage": doc.get("lineage", []),
            "gbif_id": doc.get("gbif_id"),
            "created_at": str(doc.get("created_at", "")),
        }
        if not dry_run:
            arango.upsert("taxa", arango_doc)
        count_vertices += 1

        # Create parent→child taxonomical edge
        parent_tax_id = doc.get("parent_tax_id")
        if parent_tax_id and parent_tax_id != doc.get("tax_id"):
            edge = {
                "_key": f"{parent_tax_id}_{key}",
                "_from": f"taxa/{parent_tax_id}",
                "_to": f"taxa/{key}",
                "relation": "parent_of",
            }
            if not dry_run:
                try:
                    arango.upsert("taxonomical", edge)
                    count_edges += 1
                except Exception:
                    pass  # Skip if parent not migrated yet

    logger.info(
        "[taxa] %s %d vertices, %d edges",
        "DRY" if dry_run else "migrated",
        count_vertices,
        count_edges,
    )
    return count_vertices


def migrate_document_taxon_relations(mongo_db, arango: ArangoDatabase, dry_run: bool) -> int:
    col = mongo_db["document_taxon_relations"]
    count = 0
    for doc in col.find():
        doc_key = mongo_id_to_key(doc.get("document_id", ""))
        tax_id = str(doc.get("tax_id", ""))
        edge = {
            "_key": mongo_id_to_key(doc["_id"]),
            "_from": f"documents/{doc_key}",
            "_to": f"taxa/{tax_id}",
            "relation_type": doc.get("relation_type", "studies"),
            "confidence": doc.get("confidence", 0.5),
            "evidence": doc.get("evidence", ""),
            "status": doc.get("status", "suggested"),
            "created_by": doc.get("created_by", "agent"),
            "created_at": str(doc.get("created_at", "")),
        }
        if not dry_run:
            arango.upsert("knowledge_graph", edge)
        count += 1
    logger.info(
        "[knowledge_graph edges] %s %d records",
        "DRY" if dry_run else "migrated",
        count,
    )
    return count


# ------------------------------------------------------------------
# Migration map
# ------------------------------------------------------------------

MIGRATORS = {
    "documents": migrate_documents,
    "facts": migrate_facts,
    "stylized_facts": migrate_stylized_facts,
    "fact_sf_relations": migrate_fact_sf_relations,
    "taxonomy": migrate_taxonomy,
    "document_taxon_relations": migrate_document_taxon_relations,
}


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Migrate MongoDB → ArangoDB")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--collections",
        nargs="+",
        choices=list(MIGRATORS.keys()),
        default=list(MIGRATORS.keys()),
        help="Which collections to migrate (default: all)",
    )
    parser.add_argument("--drop-existing", action="store_true", help="Drop ArangoDB collections first")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN — no data will be written ===")

    # Connect MongoDB
    logger.info("Connecting to MongoDB: %s / %s", settings.MONGODB_URL, settings.DATABASE_NAME)
    mongo_db = get_mongo_db()

    # Connect ArangoDB
    arango = ArangoDatabase()
    if not args.dry_run:
        logger.info("Connecting to ArangoDB: %s / %s", settings.ARANGO_URL, settings.ARANGO_DB_NAME)
        arango.connect()
        arango.setup_schema(drop_existing=args.drop_existing)
    else:
        logger.info("(Skipping ArangoDB connection in dry-run mode)")

    # Run migrators
    totals = {}
    for name in args.collections:
        try:
            totals[name] = MIGRATORS[name](mongo_db, arango, dry_run=args.dry_run)
        except Exception as exc:
            logger.error("Failed to migrate %s: %s", name, exc)
            totals[name] = -1

    # Summary
    logger.info("=== Migration Summary ===")
    for name, count in totals.items():
        status = "ERROR" if count < 0 else ("DRY" if args.dry_run else "OK")
        logger.info("  %-30s %s  %d", name, status, max(count, 0))

    if not args.dry_run:
        logger.info("Final ArangoDB stats: %s", arango.stats())


if __name__ == "__main__":
    main()
