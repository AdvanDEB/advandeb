"""
GraphBuilderService — materializes graph schemas and graph data into MongoDB.

Reads source collections (stylized_facts, taxonomy_nodes) and creates
GraphSchema, GraphNode, and GraphEdge documents in the database.

Usage:
    service = GraphBuilderService(db)
    await service.seed_schemas()
    await service.build_sf_graph(schema_id)
    await service.build_taxonomy_graph(schema_id, root_taxid=40674)
"""
import logging
from typing import Any, Dict, List, Optional

from bson import ObjectId

from advandeb_kb.models.graph import BUILTIN_SCHEMAS

logger = logging.getLogger(__name__)


class GraphBuilderService:
    def __init__(self, database):
        self.db = database
        self.schemas = database.graph_schemas
        self.nodes = database.graph_nodes
        self.edges = database.graph_edges

    # ------------------------------------------------------------------
    # Schema seeding
    # ------------------------------------------------------------------

    async def seed_schemas(self) -> Dict[str, Any]:
        """Upsert all BUILTIN_SCHEMAS into graph_schemas collection.

        Returns a summary of inserted / already-existing counts.
        """
        inserted = 0
        existing = 0

        for schema_def in BUILTIN_SCHEMAS:
            result = await self.schemas.update_one(
                {"name": schema_def["name"]},
                {"$setOnInsert": schema_def},
                upsert=True,
            )
            if result.upserted_id:
                inserted += 1
                logger.info("Seeded schema: %s", schema_def["name"])
            else:
                existing += 1

        logger.info("seed_schemas done — inserted=%d, existing=%d", inserted, existing)
        return {"inserted": inserted, "existing": existing}

    # ------------------------------------------------------------------
    # Schema lookup
    # ------------------------------------------------------------------

    async def get_schema_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Return the graph_schemas document with the given name, or None."""
        return await self.schemas.find_one({"name": name})

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    async def clear_graph(self, schema_id: ObjectId) -> Dict[str, int]:
        """Delete all nodes and edges for a given schema_id."""
        nr = await self.nodes.delete_many({"schema_id": schema_id})
        er = await self.edges.delete_many({"schema_id": schema_id})
        logger.info(
            "clear_graph %s — deleted %d nodes, %d edges",
            schema_id,
            nr.deleted_count,
            er.deleted_count,
        )
        return {"nodes_deleted": nr.deleted_count, "edges_deleted": er.deleted_count}

    # ------------------------------------------------------------------
    # SF-support graph
    # ------------------------------------------------------------------

    async def build_sf_graph(self, schema_id: ObjectId) -> Dict[str, Any]:
        """Build stylized-fact nodes for the sf_support schema.

        Creates one GraphNode per StylizedFact document.  No edges are
        created here — edges require ingested Facts+FactSFRelations.

        Returns a summary dict.
        """
        await self.clear_graph(schema_id)

        cursor = self.db.stylized_facts.find({})
        node_docs: List[Dict[str, Any]] = []

        async for sf in cursor:
            node_docs.append(
                {
                    "schema_id": schema_id,
                    "node_type": "stylized_fact",
                    "entity_collection": "stylized_facts",
                    "entity_id": str(sf["_id"]),
                    "label": sf.get("statement", "")[:120],
                    "properties": {
                        "category": sf.get("category", ""),
                        "status": sf.get("status", "pending"),
                        "sf_number": sf.get("sf_number"),
                    },
                }
            )

        if node_docs:
            await self.nodes.insert_many(node_docs)

        logger.info("build_sf_graph — %d nodes inserted", len(node_docs))
        return {"nodes": len(node_docs), "edges": 0}

    # ------------------------------------------------------------------
    # Taxonomical graph
    # ------------------------------------------------------------------

    async def build_taxonomy_graph(
        self,
        schema_id: ObjectId,
        root_taxid: int,
        max_nodes: int = 500,
    ) -> Dict[str, Any]:
        """Build taxon nodes + parent-child edges for the taxonomical schema.

        Fetches taxonomy_nodes whose lineage array contains root_taxid (or
        whose tax_id == root_taxid), up to max_nodes records.

        Returns a summary dict.
        """
        await self.clear_graph(schema_id)

        # Fetch the subtree: root itself plus all descendants
        cursor = self.db.taxonomy_nodes.find(
            {"$or": [{"tax_id": root_taxid}, {"lineage": root_taxid}]},
            limit=max_nodes,
        )

        tax_docs: List[Dict[str, Any]] = []
        async for taxon in cursor:
            tax_docs.append(taxon)

        if not tax_docs:
            logger.warning("build_taxonomy_graph — no taxa found for root_taxid=%d", root_taxid)
            return {"nodes": 0, "edges": 0}

        # Insert nodes, collect (tax_id → inserted _id) mapping
        node_docs: List[Dict[str, Any]] = []
        for taxon in tax_docs:
            node_docs.append(
                {
                    "schema_id": schema_id,
                    "node_type": "taxon",
                    "entity_collection": "taxonomy_nodes",
                    "entity_id": str(taxon["_id"]),
                    "label": taxon.get("name", str(taxon.get("tax_id", ""))),
                    "properties": {
                        "rank": taxon.get("rank", ""),
                        "tax_id": taxon.get("tax_id"),
                        "gbif_usage_key": taxon.get("gbif_usage_key"),
                        "common_names": taxon.get("common_names", [])[:3],
                    },
                    # Store tax_id for edge building — not part of the schema but
                    # needed transiently; we'll remove it after edge building.
                    "_tax_id": taxon.get("tax_id"),
                    "_parent_tax_id": taxon.get("parent_tax_id"),
                }
            )

        result = await self.nodes.insert_many(node_docs)
        inserted_ids = result.inserted_ids  # list of ObjectId in insertion order

        # Build tax_id → node ObjectId lookup
        taxid_to_node_id: Dict[int, ObjectId] = {}
        for i, doc in enumerate(node_docs):
            taxid_to_node_id[doc["_tax_id"]] = inserted_ids[i]

        # Clean up transient fields from DB (optional, but keeps data clean)
        await self.nodes.update_many(
            {"schema_id": schema_id},
            {"$unset": {"_tax_id": "", "_parent_tax_id": ""}},
        )

        # Insert parent-child edges
        edge_docs: List[Dict[str, Any]] = []
        for i, doc in enumerate(node_docs):
            parent_tid = doc.get("_parent_tax_id")
            if parent_tid is not None and parent_tid in taxid_to_node_id:
                edge_docs.append(
                    {
                        "schema_id": schema_id,
                        "edge_type": "is_child_of",
                        "source_node_id": inserted_ids[i],
                        "target_node_id": taxid_to_node_id[parent_tid],
                        "weight": 1.0,
                        "properties": {},
                    }
                )

        if edge_docs:
            await self.edges.insert_many(edge_docs)

        logger.info(
            "build_taxonomy_graph root=%d — %d nodes, %d edges",
            root_taxid,
            len(node_docs),
            len(edge_docs),
        )
        return {"nodes": len(node_docs), "edges": len(edge_docs)}
