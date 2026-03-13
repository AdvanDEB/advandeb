"""
Link documents to taxonomy nodes via name-index matching.

Reads documents collection, matches concept/keyword/title names against
the taxonomy name index, and writes matches to document_taxon_relations.

Run this after:
  1. import_taxonomy.py     (populate taxonomy_nodes)
  2. import_openalex_abstracts.py  (populate documents)

Usage:
    # Test: first 200 docs, Mammalia subtree
    conda run -n advandeb-modeling-assistant python3 scripts/link_documents_to_taxa.py \\
        --root-taxid 40674 --limit 200 --dry-run

    # Real run: 10 000 docs
    conda run -n advandeb-modeling-assistant python3 scripts/link_documents_to_taxa.py \\
        --root-taxid 40674 --limit 10000

    # Full corpus in overlapping batches of 5000
    for skip in $(seq 0 5000 100000); do
        conda run -n advandeb-modeling-assistant python3 scripts/link_documents_to_taxa.py \\
            --root-taxid 40674 --limit 5000 --skip $skip
    done
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.database.mongodb import mongodb
from advandeb_kb.services.kg_builder_service import KGBuilderService

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def run(
    root_taxid: int,
    limit: int,
    skip: int,
    overwrite: bool,
    dry_run: bool,
) -> None:
    await mongodb.connect()
    try:
        db = mongodb.database
        service = KGBuilderService(db)
        await service.ensure_indexes()

        logger.info("Building name index (root_taxid=%s)…", root_taxid)
        n = await service.build_name_index(root_taxid=root_taxid if root_taxid else None)
        logger.info("  %d name entries indexed", n)

        if dry_run:
            # Show what would be matched for first 5 documents
            logger.info("Dry-run — sampling 5 documents:")
            from datetime import datetime
            count = 0
            async for doc in db.documents.find({}, limit=5, skip=skip):
                relations = service._match_document(doc, datetime.utcnow())
                logger.info(
                    "  doc %s (%d chars abstract) → %d taxon matches",
                    str(doc["_id"])[-6:],
                    len(doc.get("abstract") or ""),
                    len(relations),
                )
                for rel in relations[:3]:
                    logger.info(
                        "    tax_id=%d  conf=%.2f  evidence=%r",
                        rel["tax_id"], rel["confidence"], rel["evidence"],
                    )
                count += 1
            logger.info("Dry-run complete")
            return

        logger.info("Linking documents (limit=%d, skip=%d)…", limit, skip)
        result = await service.link_documents(
            limit=limit, skip=skip, overwrite=overwrite
        )
        logger.info("Done — %s", result)

        stats = await service.get_stats()
        logger.info(
            "DB state: %d docs total, %d linked, %d relations",
            stats["total_documents"], stats["linked_documents"], stats["total_relations"],
        )
    finally:
        await mongodb.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Link documents to taxonomy nodes via name-index matching."
    )
    parser.add_argument(
        "--root-taxid",
        type=int,
        default=40674,
        help="NCBI taxonomy root ID for name index (default: 40674 = Mammalia). "
             "Use 0 to index the full taxonomy.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Max number of documents to process (default: 1000)",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Offset into documents collection (default: 0)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-link already-linked documents (upsert)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show sample matches without writing to DB",
    )
    args = parser.parse_args()

    root = args.root_taxid if args.root_taxid != 0 else None
    asyncio.run(run(root, args.limit, args.skip, args.overwrite, args.dry_run))


if __name__ == "__main__":
    main()
