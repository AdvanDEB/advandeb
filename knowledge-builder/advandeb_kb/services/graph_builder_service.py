"""
GraphBuilderService — materializes graph schemas and graph data into MongoDB.

Reads source collections (stylized_facts, taxonomy_nodes, documents, facts,
fact_sf_relations) and creates GraphSchema, GraphNode, and GraphEdge documents.

Usage:
    service = GraphBuilderService(db)
    await service.seed_schemas()
    await service.build_sf_graph(schema_id)
    await service.build_taxonomy_graph(schema_id, root_taxid=40674)
    await service.build_citation_graph(schema_id)
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
        """Build the sf_support knowledge graph.

        Node types created:
          - stylized_fact  (from stylized_facts collection — always built)
          - fact           (from facts collection — built when data exists)
          - document       (from documents collection — built when data exists)

        Edge types created:
          - extracted_from  fact → document  (via fact.document_id)
          - supports        fact → sf        (via fact_sf_relations)
          - opposes         fact → sf        (via fact_sf_relations)

        Returns a summary dict.
        """
        await self.clear_graph(schema_id)

        total_nodes = 0
        total_edges = 0

        # ---- stylized_fact nodes ----
        sf_entity_to_node: Dict[str, ObjectId] = {}
        sf_node_docs: List[Dict[str, Any]] = []
        async for sf in self.db.stylized_facts.find({}):
            sf_node_docs.append({
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
            })

        if sf_node_docs:
            result = await self.nodes.insert_many(sf_node_docs)
            for i, doc in enumerate(sf_node_docs):
                sf_entity_to_node[doc["entity_id"]] = result.inserted_ids[i]
            total_nodes += len(sf_node_docs)
            logger.info("build_sf_graph — %d stylized_fact nodes", len(sf_node_docs))

        # ---- document nodes (if documents collection has data) ----
        doc_entity_to_node: Dict[str, ObjectId] = {}
        doc_count = await self.db.documents.count_documents({})
        if doc_count > 0:
            doc_node_docs: List[Dict[str, Any]] = []
            async for doc in self.db.documents.find({}):
                doc_node_docs.append({
                    "schema_id": schema_id,
                    "node_type": "document",
                    "entity_collection": "documents",
                    "entity_id": str(doc["_id"]),
                    "label": (doc.get("title") or f"doc:{doc['_id']}")[:120],
                    "properties": {
                        "doi": doc.get("doi"),
                        "year": doc.get("year"),
                        "journal": doc.get("journal", ""),
                        "status": doc.get("processing_status", ""),
                    },
                })

            if doc_node_docs:
                result = await self.nodes.insert_many(doc_node_docs)
                for i, doc_node in enumerate(doc_node_docs):
                    doc_entity_to_node[doc_node["entity_id"]] = result.inserted_ids[i]
                total_nodes += len(doc_node_docs)
                logger.info("build_sf_graph — %d document nodes", len(doc_node_docs))

        # ---- fact nodes (if facts collection has data) ----
        fact_entity_to_node: Dict[str, ObjectId] = {}
        fact_count = await self.db.facts.count_documents({})
        if fact_count > 0:
            fact_node_docs: List[Dict[str, Any]] = []
            async for fact in self.db.facts.find({}):
                fact_node_docs.append({
                    "schema_id": schema_id,
                    "node_type": "fact",
                    "entity_collection": "facts",
                    "entity_id": str(fact["_id"]),
                    "label": fact.get("content", "")[:120],
                    "properties": {
                        "confidence": fact.get("confidence", 0.8),
                        "status": fact.get("status", "pending"),
                        "entities": (fact.get("entities") or [])[:5],
                    },
                    # Transient — used for edge building below
                    "_doc_entity_id": str(fact.get("document_id", "")),
                })

            if fact_node_docs:
                result = await self.nodes.insert_many(fact_node_docs)
                for i, fn in enumerate(fact_node_docs):
                    fact_entity_to_node[fn["entity_id"]] = result.inserted_ids[i]
                total_nodes += len(fact_node_docs)
                logger.info("build_sf_graph — %d fact nodes", len(fact_node_docs))

            # extracted_from edges: fact → document
            edge_docs: List[Dict[str, Any]] = []
            for fn in fact_node_docs:
                doc_eid = fn.get("_doc_entity_id", "")
                if doc_eid and doc_eid in doc_entity_to_node:
                    edge_docs.append({
                        "schema_id": schema_id,
                        "edge_type": "extracted_from",
                        "source_node_id": fact_entity_to_node[fn["entity_id"]],
                        "target_node_id": doc_entity_to_node[doc_eid],
                        "weight": 1.0,
                        "properties": {},
                    })

            # Clean up transient field
            await self.nodes.update_many(
                {"schema_id": schema_id, "node_type": "fact"},
                {"$unset": {"_doc_entity_id": ""}},
            )

            if edge_docs:
                await self.edges.insert_many(edge_docs)
                total_edges += len(edge_docs)
                logger.info("build_sf_graph — %d extracted_from edges", len(edge_docs))

        # ---- fact→SF edges from fact_sf_relations ----
        relation_count = await self.db.fact_sf_relations.count_documents({})
        if relation_count > 0 and fact_entity_to_node and sf_entity_to_node:
            sf_edge_docs: List[Dict[str, Any]] = []
            async for rel in self.db.fact_sf_relations.find({}):
                fact_eid = str(rel.get("fact_id", ""))
                sf_eid = str(rel.get("sf_id", ""))
                if fact_eid in fact_entity_to_node and sf_eid in sf_entity_to_node:
                    sf_edge_docs.append({
                        "schema_id": schema_id,
                        "edge_type": rel.get("relation_type", "supports"),
                        "source_node_id": fact_entity_to_node[fact_eid],
                        "target_node_id": sf_entity_to_node[sf_eid],
                        "weight": rel.get("confidence", 0.5),
                        "properties": {"status": rel.get("status", "suggested")},
                    })

            if sf_edge_docs:
                await self.edges.insert_many(sf_edge_docs)
                total_edges += len(sf_edge_docs)
                logger.info("build_sf_graph — %d supports/opposes edges", len(sf_edge_docs))

        logger.info(
            "build_sf_graph complete — %d nodes, %d edges", total_nodes, total_edges
        )
        return {"nodes": total_nodes, "edges": total_edges}

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
                    "_tax_id": taxon.get("tax_id"),
                    "_parent_tax_id": taxon.get("parent_tax_id"),
                }
            )

        result = await self.nodes.insert_many(node_docs)
        inserted_ids = result.inserted_ids

        taxid_to_node_id: Dict[int, ObjectId] = {}
        for i, doc in enumerate(node_docs):
            taxid_to_node_id[doc["_tax_id"]] = inserted_ids[i]

        await self.nodes.update_many(
            {"schema_id": schema_id},
            {"$unset": {"_tax_id": "", "_parent_tax_id": ""}},
        )

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

    # ------------------------------------------------------------------
    # Knowledge graph (taxonomy backbone + documents via agent links)
    # ------------------------------------------------------------------

    async def build_knowledge_graph(
        self,
        schema_id: ObjectId,
        root_taxid: int,
        max_nodes: int = 15000,
    ) -> Dict[str, Any]:
        """Build the unified knowledge graph schema.

        Taxon backbone:
          - Fetches the subtree rooted at root_taxid (same query as
            build_taxonomy_graph).
          - node_type is set to the taxon's *rank* (species, genus, family,
            class, …) rather than the generic "taxon" string — this gives
            visual differentiation in the canvas.
          - is_child_of edges connect each taxon to its parent.

        Document overlay:
          - Only documents that have at least one document_taxon_relation
            pointing into the fetched taxon subtree are included.
          - node_type is "document".
          - studies edges connect document → taxon (one edge per relation,
            weight = relation confidence).
          - Only relations with status "suggested" or "confirmed" are used.

        Returns a summary dict {nodes, edges, taxon_nodes, doc_nodes,
        backbone_edges, studies_edges}.
        """
        await self.clear_graph(schema_id)

        # ---- 1. Fetch taxon subtree ----
        cursor = self.db.taxonomy_nodes.find(
            {"$or": [{"tax_id": root_taxid}, {"lineage": root_taxid}]},
            limit=max_nodes,
        )
        tax_docs: List[Dict[str, Any]] = []
        async for taxon in cursor:
            tax_docs.append(taxon)

        if not tax_docs:
            logger.warning("build_knowledge_graph — no taxa for root_taxid=%d", root_taxid)
            return {"nodes": 0, "edges": 0, "taxon_nodes": 0, "doc_nodes": 0,
                    "backbone_edges": 0, "studies_edges": 0}

        # ---- 2. Insert taxon nodes (node_type = rank) ----
        taxon_node_docs: List[Dict[str, Any]] = []
        for taxon in tax_docs:
            rank = taxon.get("rank") or "no rank"
            taxon_node_docs.append({
                "schema_id": schema_id,
                "node_type": rank,          # rank becomes the visual node type
                "entity_collection": "taxonomy_nodes",
                "entity_id": str(taxon["_id"]),
                "label": taxon.get("name", str(taxon.get("tax_id", ""))),
                "properties": {
                    "rank": rank,
                    "tax_id": taxon.get("tax_id"),
                    "gbif_usage_key": taxon.get("gbif_usage_key"),
                    "common_names": taxon.get("common_names", [])[:3],
                },
                "_tax_id": taxon.get("tax_id"),
                "_parent_tax_id": taxon.get("parent_tax_id"),
            })

        result = await self.nodes.insert_many(taxon_node_docs)
        inserted_taxon_ids = result.inserted_ids

        # Build lookups
        taxid_to_node_id: Dict[int, ObjectId] = {}
        for i, doc in enumerate(taxon_node_docs):
            taxid_to_node_id[doc["_tax_id"]] = inserted_taxon_ids[i]

        await self.nodes.update_many(
            {"schema_id": schema_id},
            {"$unset": {"_tax_id": "", "_parent_tax_id": ""}},
        )

        # ---- 3. Backbone edges: is_child_of ----
        backbone_edges: List[Dict[str, Any]] = []
        for i, doc in enumerate(taxon_node_docs):
            parent_tid = doc.get("_parent_tax_id")
            if parent_tid is not None and parent_tid in taxid_to_node_id:
                backbone_edges.append({
                    "schema_id": schema_id,
                    "edge_type": "is_child_of",
                    "source_node_id": inserted_taxon_ids[i],
                    "target_node_id": taxid_to_node_id[parent_tid],
                    "weight": 1.0,
                    "properties": {},
                })

        if backbone_edges:
            await self.edges.insert_many(backbone_edges)

        # ---- 4. Document nodes via document_taxon_relations ----
        # Find all relations pointing to any taxon in the fetched subtree
        subtree_taxids = set(taxid_to_node_id.keys())
        included_taxids_in_subtree = {"$in": list(subtree_taxids)}

        doc_id_to_relations: Dict[str, List[Dict]] = {}
        async for rel in self.db.document_taxon_relations.find({
            "tax_id": included_taxids_in_subtree,
            "status": {"$in": ["suggested", "confirmed"]},
        }):
            doc_eid = str(rel["document_id"])
            doc_id_to_relations.setdefault(doc_eid, []).append(rel)

        doc_nodes_inserted = 0
        studies_edges_inserted = 0

        if doc_id_to_relations:
            from bson import ObjectId as _OID

            # Fetch only the documents that have relations in this subtree
            doc_oids = [_OID(eid) for eid in doc_id_to_relations if _OID.is_valid(eid)]
            doc_entity_to_node: Dict[str, ObjectId] = {}
            doc_node_docs: List[Dict[str, Any]] = []

            async for doc in self.db.documents.find({"_id": {"$in": doc_oids}}):
                doc_node_docs.append({
                    "schema_id": schema_id,
                    "node_type": "document",
                    "entity_collection": "documents",
                    "entity_id": str(doc["_id"]),
                    "label": (doc.get("title") or f"doc:{doc['_id']}")[:120],
                    "properties": {
                        "doi": doc.get("doi"),
                        "year": doc.get("year"),
                        "authors": (doc.get("authors") or [])[:3],
                        "journal": doc.get("journal", ""),
                        "general_domain": doc.get("general_domain", ""),
                    },
                })

            if doc_node_docs:
                result = await self.nodes.insert_many(doc_node_docs)
                for i, dn in enumerate(doc_node_docs):
                    doc_entity_to_node[dn["entity_id"]] = result.inserted_ids[i]
                doc_nodes_inserted = len(doc_node_docs)

            # studies edges: document → taxon
            studies_edge_docs: List[Dict[str, Any]] = []
            for doc_eid, relations in doc_id_to_relations.items():
                if doc_eid not in doc_entity_to_node:
                    continue
                doc_node_id = doc_entity_to_node[doc_eid]
                for rel in relations:
                    tax_id = rel.get("tax_id")
                    if tax_id in taxid_to_node_id:
                        studies_edge_docs.append({
                            "schema_id": schema_id,
                            "edge_type": "studies",
                            "source_node_id": doc_node_id,
                            "target_node_id": taxid_to_node_id[tax_id],
                            "weight": rel.get("confidence", 0.5),
                            "properties": {
                                "evidence": rel.get("evidence", ""),
                                "status": rel.get("status", "suggested"),
                                "created_by": rel.get("created_by", "agent"),
                            },
                        })

            if studies_edge_docs:
                await self.edges.insert_many(studies_edge_docs)
                studies_edges_inserted = len(studies_edge_docs)

        total_nodes = len(taxon_node_docs) + doc_nodes_inserted
        total_edges = len(backbone_edges) + studies_edges_inserted

        logger.info(
            "build_knowledge_graph root=%d — %d taxon nodes (%d backbone edges), "
            "%d doc nodes (%d studies edges)",
            root_taxid,
            len(taxon_node_docs), len(backbone_edges),
            doc_nodes_inserted, studies_edges_inserted,
        )
        return {
            "nodes": total_nodes,
            "edges": total_edges,
            "taxon_nodes": len(taxon_node_docs),
            "doc_nodes": doc_nodes_inserted,
            "backbone_edges": len(backbone_edges),
            "studies_edges": studies_edges_inserted,
        }

    # ------------------------------------------------------------------
    # Citation graph
    # ------------------------------------------------------------------

    async def build_citation_graph(self, schema_id: ObjectId) -> Dict[str, Any]:
        """Build document citation network for the citation schema.

        Creates one GraphNode per Document.  Citation edges (type 'cites')
        are built from a 'references' field on each document document — a list
        of DOI strings.  If no references data exists, the graph will contain
        only nodes (useful for browsing the document corpus).

        Returns a summary dict.
        """
        await self.clear_graph(schema_id)

        doc_list: List[Dict[str, Any]] = []
        async for doc in self.db.documents.find({}):
            doc_list.append(doc)

        if not doc_list:
            logger.info("build_citation_graph — documents collection is empty")
            return {"nodes": 0, "edges": 0}

        # DOI → mongo _id for cross-reference resolution
        doi_to_doc_id: Dict[str, ObjectId] = {}
        for doc in doc_list:
            if doc.get("doi"):
                doi_to_doc_id[doc["doi"]] = doc["_id"]

        node_docs: List[Dict[str, Any]] = []
        for doc in doc_list:
            node_docs.append({
                "schema_id": schema_id,
                "node_type": "document",
                "entity_collection": "documents",
                "entity_id": str(doc["_id"]),
                "label": (doc.get("title") or f"doc:{doc['_id']}")[:120],
                "properties": {
                    "doi": doc.get("doi"),
                    "year": doc.get("year"),
                    "authors": (doc.get("authors") or [])[:3],
                    "journal": doc.get("journal", ""),
                    "source_type": doc.get("source_type", ""),
                    "status": doc.get("processing_status", ""),
                },
            })

        result = await self.nodes.insert_many(node_docs)
        inserted_ids = result.inserted_ids

        # entity_id (str) → inserted node ObjectId
        entity_to_node: Dict[str, ObjectId] = {}
        for i, nd in enumerate(node_docs):
            entity_to_node[nd["entity_id"]] = inserted_ids[i]

        # DOI → node ObjectId
        doi_to_node: Dict[str, ObjectId] = {}
        for doc in doc_list:
            if doc.get("doi") and str(doc["_id"]) in entity_to_node:
                doi_to_node[doc["doi"]] = entity_to_node[str(doc["_id"])]

        # Build citation edges from doc['references'] — list of DOI strings
        edge_docs: List[Dict[str, Any]] = []
        for doc in doc_list:
            source_node_id = entity_to_node[str(doc["_id"])]
            for ref_doi in (doc.get("references") or []):
                if isinstance(ref_doi, str) and ref_doi in doi_to_node:
                    edge_docs.append({
                        "schema_id": schema_id,
                        "edge_type": "cites",
                        "source_node_id": source_node_id,
                        "target_node_id": doi_to_node[ref_doi],
                        "weight": 1.0,
                        "properties": {},
                    })

        if edge_docs:
            await self.edges.insert_many(edge_docs)

        logger.info(
            "build_citation_graph — %d nodes, %d edges (%d docs had DOIs)",
            len(node_docs),
            len(edge_docs),
            len(doi_to_doc_id),
        )
        return {"nodes": len(node_docs), "edges": len(edge_docs)}
