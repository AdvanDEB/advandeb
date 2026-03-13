"""
Build materialized graph data in MongoDB.

Seeds graph schemas first, then builds the chosen graph type.

Usage:
    conda run -n advandeb-modeling-assistant python3 scripts/build_graphs.py --schema sf_support
    conda run -n advandeb-modeling-assistant python3 scripts/build_graphs.py --schema taxonomical --root-taxid 40674
    conda run -n advandeb-modeling-assistant python3 scripts/build_graphs.py --schema taxonomical --root-taxid 40674 --max-nodes 1000
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advandeb_kb.database.mongodb import mongodb
from advandeb_kb.services.graph_builder_service import GraphBuilderService

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCHEMA_CHOICES = ["sf_support", "taxonomical", "citation", "knowledge_graph"]


async def run(schema: str, root_taxid: int, max_nodes: int) -> None:
    await mongodb.connect()
    db = mongodb.database
    service = GraphBuilderService(db)

    logger.info("Seeding graph schemas...")
    seed_result = await service.seed_schemas()
    logger.info("  %s", seed_result)

    schema_doc = await service.get_schema_by_name(schema)
    if schema_doc is None:
        logger.error("Schema '%s' not found in database — did seed_schemas() run?", schema)
        await mongodb.disconnect()
        sys.exit(1)

    schema_id = schema_doc["_id"]
    logger.info("Building '%s' graph (schema_id=%s)...", schema, schema_id)

    if schema == "sf_support":
        result = await service.build_sf_graph(schema_id)
    elif schema == "taxonomical":
        if root_taxid is None:
            logger.error("--root-taxid is required for the taxonomical schema.")
            await mongodb.disconnect()
            sys.exit(1)
        result = await service.build_taxonomy_graph(schema_id, root_taxid, max_nodes)
    elif schema == "citation":
        result = await service.build_citation_graph(schema_id)
    elif schema == "knowledge_graph":
        if root_taxid is None:
            logger.error("--root-taxid is required for knowledge_graph schema.")
            await mongodb.disconnect()
            sys.exit(1)
        result = await service.build_knowledge_graph(schema_id, root_taxid, max_nodes)
    else:
        logger.error("Unknown schema: %s. Choose from: %s", schema, SCHEMA_CHOICES)
        await mongodb.disconnect()
        sys.exit(1)

    logger.info("Done — %s", result)
    await mongodb.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Build materialized graph data in MongoDB.")
    parser.add_argument(
        "--schema",
        required=True,
        choices=SCHEMA_CHOICES,
        help="Which graph schema to build.",
    )
    parser.add_argument(
        "--root-taxid",
        type=int,
        default=None,
        help="NCBI taxonomy ID of the root node (required for --schema taxonomical). "
             "40674 = Mammalia.",
    )
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=500,
        help="Maximum number of taxonomy nodes to fetch (default: 500).",
    )
    args = parser.parse_args()
    asyncio.run(run(args.schema, args.root_taxid, args.max_nodes))


if __name__ == "__main__":
    main()
