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
    await service.build_physiological_graph(schema_id)
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
            _cat = sf.get("category") or "uncategorized"
            sf_node_docs.append({
                "schema_id": schema_id,
                "node_type": "stylized_fact",
                "entity_collection": "stylized_facts",
                "entity_id": str(sf["_id"]),
                "label": sf.get("statement", "")[:120],
                "properties": {
                    "category": _cat,
                    "status": sf.get("status", "pending"),
                    "sf_number": sf.get("sf_number"),
                    "cluster_id": f"sf:{_cat}",
                },
            })

        if sf_node_docs:
            result = await self.nodes.insert_many(sf_node_docs)
            for i, doc in enumerate(sf_node_docs):
                sf_entity_to_node[doc["entity_id"]] = result.inserted_ids[i]
            total_nodes += len(sf_node_docs)
            logger.info("build_sf_graph — %d stylized_fact nodes", len(sf_node_docs))
        doc_entity_to_node: Dict[str, ObjectId] = {}
        doc_count = await self.db.documents.count_documents({})
        if doc_count > 0:
            doc_node_docs: List[Dict[str, Any]] = []
            async for doc in self.db.documents.find({}):
                _journal = doc.get("journal") or "unknown"
                doc_node_docs.append({
                    "schema_id": schema_id,
                    "node_type": "document",
                    "entity_collection": "documents",
                    "entity_id": str(doc["_id"]),
                    "label": (doc.get("title") or f"doc:{doc['_id']}")[:120],
                    "properties": {
                        "doi": doc.get("doi"),
                        "year": doc.get("year"),
                        "journal": _journal,
                        "status": doc.get("processing_status", ""),
                        "cluster_id": f"doc:{_journal}",
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
                        "cluster_id": "fact",
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
                        "cluster_id": f"rank:{taxon.get('rank', 'unknown')}",
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
    # Knowledge graph (full integrated graph — all node and edge types)
    # ------------------------------------------------------------------

    async def build_knowledge_graph(
        self,
        schema_id: ObjectId,
        root_taxid: int,
        max_nodes: int = 15000,
    ) -> Dict[str, Any]:
        """Build the full integrated knowledge graph schema.

        Node types created:
          - stylized_fact  (from stylized_facts collection)
          - fact           (from facts collection)
          - document       (from documents collection — only those linked to
                           taxa in the fetched subtree)
          - taxon by rank  (from taxonomy_nodes — node_type = rank field,
                           e.g. "species", "genus", "family")

        Edge types created:
          - extracted_from   fact → document     (via fact.document_id)
          - supports         fact → sf           (via fact_sf_relations)
          - opposes          fact → sf           (via fact_sf_relations)
          - is_child_of      taxon → taxon       (parent-child backbone)
          - studies          document → taxon    (via document_taxon_relations)
          - cites            document → document (via doc.references DOI list)
          - regulates        sf → sf             (via sf_sf_relations if present)
          - depends_on       sf → sf             (via sf_sf_relations if present)
          - exhibited_by     sf → taxon          (via sf_taxon_relations if present)

        Every node has a `cluster_id` property for frontend coloring:
          - stylized_fact: "sf:<category>"   (or "sf:uncategorized")
          - fact:          "fact"
          - document:      "doc:<general_domain>" (or "doc:unknown")
          - taxon:         "taxon:<rank>"    (e.g. "taxon:species")

        Returns a summary dict with per-type counts.
        """
        await self.clear_graph(schema_id)

        from bson import ObjectId as _OID

        # ================================================================
        # PART A — Taxon nodes
        # ================================================================
        # Strategy: collect taxa directly referenced by documents, then expand
        # to all their lineage ancestors for a connected tree.

        referenced_taxids: set = set()
        async for rel in self.db.document_taxon_relations.find(
            {"status": {"$in": ["suggested", "confirmed"]}},
            {"tax_id": 1},
        ):
            referenced_taxids.add(rel["tax_id"])

        # Even if no document relations exist, fall back to subtree of root_taxid
        if not referenced_taxids:
            logger.warning(
                "build_knowledge_graph — no document_taxon_relations; "
                "using raw root_taxid=%d subtree",
                root_taxid,
            )
            async for taxon in self.db.taxonomy_nodes.find(
                {"$or": [{"tax_id": root_taxid}, {"lineage": root_taxid}]},
                {"tax_id": 1},
                limit=max_nodes,
            ):
                referenced_taxids.add(taxon["tax_id"])

        # Expand to ancestors for a connected tree
        ancestor_taxids: set = set()
        async for taxon in self.db.taxonomy_nodes.find(
            {"tax_id": {"$in": list(referenced_taxids)}},
            {"tax_id": 1, "lineage": 1},
        ):
            for tid in (taxon.get("lineage") or []):
                ancestor_taxids.add(tid)
            ancestor_taxids.add(taxon["tax_id"])

        all_taxids_needed = list((referenced_taxids | ancestor_taxids))[:max_nodes]

        tax_docs: List[Dict[str, Any]] = []
        async for taxon in self.db.taxonomy_nodes.find(
            {"tax_id": {"$in": all_taxids_needed}},
        ):
            tax_docs.append(taxon)

        taxon_node_docs: List[Dict[str, Any]] = []
        for taxon in tax_docs:
            rank = taxon.get("rank") or "no rank"
            taxon_node_docs.append({
                "schema_id": schema_id,
                "node_type": rank,
                "entity_collection": "taxonomy_nodes",
                "entity_id": str(taxon["_id"]),
                "label": taxon.get("name", str(taxon.get("tax_id", ""))),
                "properties": {
                    "rank": rank,
                    "tax_id": taxon.get("tax_id"),
                    "gbif_usage_key": taxon.get("gbif_usage_key"),
                    "common_names": taxon.get("common_names", [])[:3],
                    "cluster_id": f"taxon:{rank}",
                },
                "_tax_id": taxon.get("tax_id"),
                "_parent_tax_id": taxon.get("parent_tax_id"),
            })

        taxid_to_node_id: Dict[int, ObjectId] = {}
        inserted_taxon_ids: List[ObjectId] = []
        if taxon_node_docs:
            result = await self.nodes.insert_many(taxon_node_docs)
            inserted_taxon_ids = result.inserted_ids
            for i, doc in enumerate(taxon_node_docs):
                taxid_to_node_id[doc["_tax_id"]] = inserted_taxon_ids[i]

        await self.nodes.update_many(
            {"schema_id": schema_id},
            {"$unset": {"_tax_id": "", "_parent_tax_id": ""}},
        )

        logger.info(
            "build_knowledge_graph — %d taxon nodes (root_taxid=%d)",
            len(taxon_node_docs), root_taxid,
        )

        # ================================================================
        # PART B — Stylized-fact nodes
        # ================================================================
        sf_docs: List[Dict[str, Any]] = []
        async for sf in self.db.stylized_facts.find({}):
            sf_docs.append(sf)

        sf_node_docs: List[Dict[str, Any]] = []
        for sf in sf_docs:
            category = sf.get("category") or "uncategorized"
            sf_node_docs.append({
                "schema_id": schema_id,
                "node_type": "stylized_fact",
                "entity_collection": "stylized_facts",
                "entity_id": str(sf["_id"]),
                "label": sf.get("statement", "")[:120],
                "properties": {
                    "category": category,
                    "status": sf.get("status", "pending"),
                    "sf_number": sf.get("sf_number"),
                    "cluster_id": f"sf:{category}",
                },
            })

        sf_entity_to_node: Dict[str, ObjectId] = {}
        if sf_node_docs:
            result = await self.nodes.insert_many(sf_node_docs)
            for i, nd in enumerate(sf_node_docs):
                sf_entity_to_node[nd["entity_id"]] = result.inserted_ids[i]

        logger.info("build_knowledge_graph — %d stylized_fact nodes", len(sf_node_docs))

        # ================================================================
        # PART C — Fact nodes
        # ================================================================
        fact_docs: List[Dict[str, Any]] = []
        async for fact in self.db.facts.find({}):
            fact_docs.append(fact)

        fact_node_docs: List[Dict[str, Any]] = []
        for fact in fact_docs:
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
                    "cluster_id": "fact",
                },
                "_doc_entity_id": str(fact.get("document_id", "")),
            })

        fact_entity_to_node: Dict[str, ObjectId] = {}
        if fact_node_docs:
            result = await self.nodes.insert_many(fact_node_docs)
            for i, fn in enumerate(fact_node_docs):
                fact_entity_to_node[fn["entity_id"]] = result.inserted_ids[i]

        logger.info("build_knowledge_graph — %d fact nodes", len(fact_node_docs))

        # ================================================================
        # PART D — Document nodes (only those linked to the taxon subtree)
        # ================================================================
        subtree_taxids = set(taxid_to_node_id.keys())
        doc_id_to_taxon_rels: Dict[str, List[Dict]] = {}
        if subtree_taxids:
            async for rel in self.db.document_taxon_relations.find({
                "tax_id": {"$in": list(subtree_taxids)},
                "status": {"$in": ["suggested", "confirmed"]},
            }):
                doc_eid = str(rel["document_id"])
                doc_id_to_taxon_rels.setdefault(doc_eid, []).append(rel)

        # Also include documents referenced by facts (even if not in taxon rels)
        fact_doc_eids: set = set()
        for fn in fact_node_docs:
            d = fn.get("_doc_entity_id", "")
            if d:
                fact_doc_eids.add(d)

        all_doc_eids = set(doc_id_to_taxon_rels.keys()) | fact_doc_eids
        doc_oids = [_OID(eid) for eid in all_doc_eids if _OID.is_valid(eid)]

        doc_entity_to_node: Dict[str, ObjectId] = {}
        doc_node_docs: List[Dict[str, Any]] = []
        doi_to_node: Dict[str, ObjectId] = {}  # built after insert for cites edges

        if doc_oids:
            async for doc in self.db.documents.find({"_id": {"$in": doc_oids}}):
                general_domain = doc.get("general_domain") or "unknown"
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
                        "general_domain": general_domain,
                        "cluster_id": f"doc:{general_domain}",
                    },
                    "_doi": doc.get("doi"),
                    "_references": doc.get("references") or [],
                })

        if doc_node_docs:
            result = await self.nodes.insert_many(doc_node_docs)
            for i, dn in enumerate(doc_node_docs):
                eid = dn["entity_id"]
                doc_entity_to_node[eid] = result.inserted_ids[i]
                if dn.get("_doi"):
                    doi_to_node[dn["_doi"]] = result.inserted_ids[i]

        # Clean up transient fact fields
        await self.nodes.update_many(
            {"schema_id": schema_id, "node_type": "fact"},
            {"$unset": {"_doc_entity_id": ""}},
        )

        logger.info("build_knowledge_graph — %d document nodes", len(doc_node_docs))

        # ================================================================
        # PART E — Edges
        # ================================================================
        all_edges: List[Dict[str, Any]] = []

        # ---- E1: is_child_of (taxon → parent taxon) ----
        backbone_count = 0
        for i, doc in enumerate(taxon_node_docs):
            parent_tid = doc.get("_parent_tax_id")
            if parent_tid is not None and parent_tid in taxid_to_node_id:
                all_edges.append({
                    "schema_id": schema_id,
                    "edge_type": "is_child_of",
                    "source_node_id": inserted_taxon_ids[i],
                    "target_node_id": taxid_to_node_id[parent_tid],
                    "weight": 1.0,
                    "properties": {},
                })
                backbone_count += 1

        # ---- E2: studies (document → taxon) ----
        studies_count = 0
        for doc_eid, relations in doc_id_to_taxon_rels.items():
            if doc_eid not in doc_entity_to_node:
                continue
            doc_node_id = doc_entity_to_node[doc_eid]
            for rel in relations:
                tax_id = rel.get("tax_id")
                if tax_id in taxid_to_node_id:
                    all_edges.append({
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
                    studies_count += 1

        # ---- E3: extracted_from (fact → document) ----
        extracted_count = 0
        for fn in fact_node_docs:
            doc_eid = fn.get("_doc_entity_id", "")
            if doc_eid and doc_eid in doc_entity_to_node and fn["entity_id"] in fact_entity_to_node:
                all_edges.append({
                    "schema_id": schema_id,
                    "edge_type": "extracted_from",
                    "source_node_id": fact_entity_to_node[fn["entity_id"]],
                    "target_node_id": doc_entity_to_node[doc_eid],
                    "weight": 1.0,
                    "properties": {},
                })
                extracted_count += 1

        # ---- E4: supports / opposes (fact → sf) ----
        sf_relation_count = 0
        relation_count = await self.db.fact_sf_relations.count_documents({})
        if relation_count > 0 and fact_entity_to_node and sf_entity_to_node:
            async for rel in self.db.fact_sf_relations.find({}):
                fact_eid = str(rel.get("fact_id", ""))
                sf_eid = str(rel.get("sf_id", ""))
                if fact_eid in fact_entity_to_node and sf_eid in sf_entity_to_node:
                    all_edges.append({
                        "schema_id": schema_id,
                        "edge_type": rel.get("relation_type", "supports"),
                        "source_node_id": fact_entity_to_node[fact_eid],
                        "target_node_id": sf_entity_to_node[sf_eid],
                        "weight": rel.get("confidence", 0.5),
                        "properties": {"status": rel.get("status", "suggested")},
                    })
                    sf_relation_count += 1

        # ---- E5: cites (document → document via references DOIs) ----
        cites_count = 0
        for dn in doc_node_docs:
            source_node_id = doc_entity_to_node.get(dn["entity_id"])
            if not source_node_id:
                continue
            for ref_doi in (dn.get("_references") or []):
                if isinstance(ref_doi, str) and ref_doi in doi_to_node:
                    all_edges.append({
                        "schema_id": schema_id,
                        "edge_type": "cites",
                        "source_node_id": source_node_id,
                        "target_node_id": doi_to_node[ref_doi],
                        "weight": 1.0,
                        "properties": {},
                    })
                    cites_count += 1

        # Clean up transient doc fields
        await self.nodes.update_many(
            {"schema_id": schema_id, "node_type": "document"},
            {"$unset": {"_doi": "", "_references": ""}},
        )

        # ---- E6: regulates / depends_on (sf → sf via sf_sf_relations) ----
        regulates_count = 0
        depends_count = 0
        try:
            sf_sf_count = await self.db.sf_sf_relations.count_documents({})
            if sf_sf_count > 0 and sf_entity_to_node:
                async for rel in self.db.sf_sf_relations.find({}):
                    source_sf_eid = str(rel.get("source_sf_id", ""))
                    target_sf_eid = str(rel.get("target_sf_id", ""))
                    rel_type = rel.get("relation_type", "regulates")
                    if source_sf_eid in sf_entity_to_node and target_sf_eid in sf_entity_to_node:
                        all_edges.append({
                            "schema_id": schema_id,
                            "edge_type": rel_type,
                            "source_node_id": sf_entity_to_node[source_sf_eid],
                            "target_node_id": sf_entity_to_node[target_sf_eid],
                            "weight": rel.get("confidence", 0.5),
                            "properties": {},
                        })
                        if rel_type == "regulates":
                            regulates_count += 1
                        else:
                            depends_count += 1
        except Exception:
            logger.debug("build_knowledge_graph — sf_sf_relations collection not found; skipping")

        # ---- E7: exhibited_by (sf → taxon via sf_taxon_relations) ----
        exhibited_count = 0
        try:
            sf_taxon_count = await self.db.sf_taxon_relations.count_documents({})
            if sf_taxon_count > 0 and sf_entity_to_node and taxid_to_node_id:
                async for rel in self.db.sf_taxon_relations.find({}):
                    sf_eid = str(rel.get("sf_id", ""))
                    tax_id = rel.get("tax_id")
                    if sf_eid in sf_entity_to_node and tax_id in taxid_to_node_id:
                        all_edges.append({
                            "schema_id": schema_id,
                            "edge_type": "exhibited_by",
                            "source_node_id": sf_entity_to_node[sf_eid],
                            "target_node_id": taxid_to_node_id[tax_id],
                            "weight": rel.get("confidence", 0.5),
                            "properties": {},
                        })
                        exhibited_count += 1
        except Exception:
            logger.debug("build_knowledge_graph — sf_taxon_relations collection not found; skipping")

        # ---- Insert all edges in one batch ----
        if all_edges:
            await self.edges.insert_many(all_edges)

        total_nodes = (
            len(taxon_node_docs) + len(sf_node_docs)
            + len(fact_node_docs) + len(doc_node_docs)
        )
        total_edges = len(all_edges)

        logger.info(
            "build_knowledge_graph root=%d — "
            "%d taxon, %d sf, %d fact, %d doc nodes | "
            "%d backbone, %d studies, %d extracted_from, %d sf_rel, "
            "%d cites, %d regulates, %d depends_on, %d exhibited_by edges",
            root_taxid,
            len(taxon_node_docs), len(sf_node_docs),
            len(fact_node_docs), len(doc_node_docs),
            backbone_count, studies_count, extracted_count, sf_relation_count,
            cites_count, regulates_count, depends_count, exhibited_count,
        )
        return {
            "nodes": total_nodes,
            "edges": total_edges,
            "taxon_nodes": len(taxon_node_docs),
            "sf_nodes": len(sf_node_docs),
            "fact_nodes": len(fact_node_docs),
            "doc_nodes": len(doc_node_docs),
            "backbone_edges": backbone_count,
            "studies_edges": studies_count,
            "extracted_from_edges": extracted_count,
            "sf_relation_edges": sf_relation_count,
            "cites_edges": cites_count,
            "regulates_edges": regulates_count,
            "depends_on_edges": depends_count,
            "exhibited_by_edges": exhibited_count,
        }

    # ------------------------------------------------------------------
    # Citation graph
    # ------------------------------------------------------------------

    async def build_citation_graph(self, schema_id: ObjectId) -> Dict[str, Any]:
        """Build document citation network for the citation schema.

        Creates one GraphNode per Document.

        Edge-building strategy (two phases):

        **Phase 1 — DOI-based cites edges:**
        Citation edges (type 'cites') are built from a 'references' field on
        each document — a list of DOI strings.  This is the bibliographically
        correct method; it requires that the ingestion pipeline populates
        doc['references'].

        **Phase 2 — Taxon-overlap fallback (when Phase 1 yields < 10 edges):**
        If fewer than 10 DOI-based edges were created (i.e. references data is
        not populated yet), a similarity-based fallback builds 'cites' edges
        between documents that study overlapping taxa.  Similarity is computed
        as Jaccard overlap of their taxon sets (from document_taxon_relations).
        Only pairs with Jaccard ≥ 0.2 and within each document's top-5 most
        similar peers are included.  These edges carry
        `properties.method = "taxon_overlap"` to distinguish them from real
        bibliographic cites edges.

        Returns a summary dict.
        """
        await self.clear_graph(schema_id)

        doc_list: List[Dict[str, Any]] = []
        async for doc in self.db.documents.find({}):
            doc_list.append(doc)

        if not doc_list:
            logger.info("build_citation_graph — documents collection is empty")
            return {"nodes": 0, "edges": 0, "doi_edges": 0, "taxon_overlap_edges": 0}

        # DOI → mongo _id for cross-reference resolution
        doi_to_doc_id: Dict[str, ObjectId] = {}
        for doc in doc_list:
            if doc.get("doi"):
                doi_to_doc_id[doc["doi"]] = doc["_id"]

        node_docs: List[Dict[str, Any]] = []
        for doc in doc_list:
            _domain = doc.get("general_domain") or "unknown"
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
                    "cluster_id": f"domain:{_domain}",
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

        # ---- Phase 1: DOI-based cites edges ----
        edge_docs: List[Dict[str, Any]] = []
        warned_no_refs = False
        for doc in doc_list:
            source_node_id = entity_to_node[str(doc["_id"])]
            refs = doc.get("references") or []
            if not refs and not warned_no_refs:
                logger.warning(
                    "build_citation_graph — no 'references' field found on documents; "
                    "will attempt taxon-overlap fallback. Populate doc['references'] as a list "
                    "of DOI strings during ingestion to enable bibliographic citation links."
                )
                warned_no_refs = True
            for ref_doi in refs:
                if isinstance(ref_doi, str) and ref_doi in doi_to_node:
                    edge_docs.append({
                        "schema_id": schema_id,
                        "edge_type": "cites",
                        "source_node_id": source_node_id,
                        "target_node_id": doi_to_node[ref_doi],
                        "weight": 1.0,
                        "properties": {"method": "doi"},
                    })

        doi_edge_count = len(edge_docs)
        taxon_overlap_count = 0

        # ---- Phase 2: Taxon-overlap fallback (only when < 10 DOI edges) ----
        if doi_edge_count < 10:
            logger.info(
                "build_citation_graph — only %d DOI edges; computing taxon-overlap fallback",
                doi_edge_count,
            )
            # Build doc_id → set(tax_id) from document_taxon_relations
            doc_eid_to_taxids: Dict[str, set] = {}
            async for rel in self.db.document_taxon_relations.find(
                {"status": {"$in": ["suggested", "confirmed"]}},
                {"document_id": 1, "tax_id": 1},
            ):
                doc_eid = str(rel["document_id"])
                doc_eid_to_taxids.setdefault(doc_eid, set()).add(rel["tax_id"])

            # Only consider documents that have at least one taxon relation
            eligible_doc_eids = [
                eid for eid in doc_eid_to_taxids if eid in entity_to_node
            ]

            if len(eligible_doc_eids) >= 2:
                # Compute pairwise Jaccard; keep top-5 per document
                from collections import defaultdict

                # per-doc best-5 peers sorted by descending jaccard
                top_peers: Dict[str, List[tuple]] = defaultdict(list)

                for i in range(len(eligible_doc_eids)):
                    eid_a = eligible_doc_eids[i]
                    taxids_a = doc_eid_to_taxids[eid_a]
                    for j in range(i + 1, len(eligible_doc_eids)):
                        eid_b = eligible_doc_eids[j]
                        taxids_b = doc_eid_to_taxids[eid_b]
                        inter = len(taxids_a & taxids_b)
                        if inter == 0:
                            continue
                        union = len(taxids_a | taxids_b)
                        jaccard = inter / union if union > 0 else 0.0
                        if jaccard >= 0.2:
                            top_peers[eid_a].append((jaccard, eid_b))
                            top_peers[eid_b].append((jaccard, eid_a))

                # For each document emit at most top-5 edges (deduplicated)
                seen_pairs: set = set()
                for eid_a, peers in top_peers.items():
                    peers.sort(key=lambda x: -x[0])
                    for jaccard, eid_b in peers[:5]:
                        pair = tuple(sorted([eid_a, eid_b]))
                        if pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)
                        edge_docs.append({
                            "schema_id": schema_id,
                            "edge_type": "cites",
                            "source_node_id": entity_to_node[eid_a],
                            "target_node_id": entity_to_node[eid_b],
                            "weight": round(jaccard, 4),
                            "properties": {"method": "taxon_overlap"},
                        })
                        taxon_overlap_count += 1

                logger.info(
                    "build_citation_graph — taxon-overlap fallback: %d edges from %d eligible docs",
                    taxon_overlap_count, len(eligible_doc_eids),
                )
            else:
                logger.info(
                    "build_citation_graph — not enough docs with taxon relations for overlap (%d)",
                    len(eligible_doc_eids),
                )

        if edge_docs:
            await self.edges.insert_many(edge_docs)

        total_edges = doi_edge_count + taxon_overlap_count
        logger.info(
            "build_citation_graph — %d nodes, %d total edges (%d DOI, %d taxon_overlap, %d docs had DOIs)",
            len(node_docs), total_edges, doi_edge_count, taxon_overlap_count, len(doi_to_doc_id),
        )
        return {
            "nodes": len(node_docs),
            "edges": total_edges,
            "doi_edges": doi_edge_count,
            "taxon_overlap_edges": taxon_overlap_count,
        }

    # ------------------------------------------------------------------
    # Physiological-process graph
    # ------------------------------------------------------------------

    async def build_physiological_graph(
        self,
        schema_id: ObjectId,
        root_taxid: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Build the physiological_process graph.

        Node types created:
          - stylized_fact  (all SFs from stylized_facts collection)
          - taxon          (only taxa linked to at least one SF via the
                           fact→document→document_taxon_relation chain)

        Edge types created:
          - exhibited_by   stylized_fact → taxon
                           Weight = max confidence of any supporting/opposing
                           fact_sf_relation for that SF whose source document
                           is linked to the taxon.

        Edge types NOT yet generated (no source data exists):
          - regulates      stylized_fact → stylized_fact  (future: sf_relations)
          - depends_on     stylized_fact → stylized_fact  (future: sf_relations)

        Derivation of exhibited_by edges:
          fact_sf_relations  fact_id → sf_id
              ↓ (fact.document_id)
          documents          _id → document
              ↓ (document_taxon_relations)
          document_taxon_relations  document_id → tax_id

        Only document_taxon_relations with status 'suggested' or 'confirmed'
        are considered.  If root_taxid is given, only taxa that are in that
        subtree (tax_id == root_taxid or root_taxid in lineage) are included.

        Returns a summary dict.
        """
        await self.clear_graph(schema_id)

        # ---- 1. Stylized-fact nodes (always all SFs) ----
        sf_docs: List[Dict[str, Any]] = []
        async for sf in self.db.stylized_facts.find({}):
            sf_docs.append(sf)

        if not sf_docs:
            logger.info("build_physiological_graph — stylized_facts collection is empty")
            return {
                "nodes": 0, "edges": 0,
                "sf_nodes": 0, "taxon_nodes": 0,
                "exhibited_by_edges": 0,
            }

        sf_node_docs: List[Dict[str, Any]] = []
        for sf in sf_docs:
            _cat = sf.get("category") or "uncategorized"
            sf_node_docs.append({
                "schema_id": schema_id,
                "node_type": "stylized_fact",
                "entity_collection": "stylized_facts",
                "entity_id": str(sf["_id"]),
                "label": sf.get("statement", "")[:120],
                "properties": {
                    "category": _cat,
                    "status": sf.get("status", "pending"),
                    "sf_number": sf.get("sf_number"),
                    "cluster_id": f"sf:{_cat}",
                },
            })

        result = await self.nodes.insert_many(sf_node_docs)
        sf_entity_to_node: Dict[str, ObjectId] = {}
        for i, nd in enumerate(sf_node_docs):
            sf_entity_to_node[nd["entity_id"]] = result.inserted_ids[i]

        logger.info("build_physiological_graph — %d stylized_fact nodes", len(sf_node_docs))

        # ---- 2. Derive exhibited_by: SF → taxon via fact chain ----
        # Step 2a: build sf_id → set(fact_id) mapping from fact_sf_relations
        # (supports + opposes both count — the SF is exhibited regardless of direction)
        sf_eid_to_fact_eids: Dict[str, set] = {}
        fact_eid_to_sf_eids: Dict[str, set] = {}
        fact_eid_to_conf: Dict[str, float] = {}

        async for rel in self.db.fact_sf_relations.find({}):
            sf_eid = str(rel.get("sf_id", ""))
            fact_eid = str(rel.get("fact_id", ""))
            if not sf_eid or not fact_eid:
                continue
            sf_eid_to_fact_eids.setdefault(sf_eid, set()).add(fact_eid)
            fact_eid_to_sf_eids.setdefault(fact_eid, set()).add(sf_eid)
            # track max confidence per fact→sf pair
            current = fact_eid_to_conf.get(fact_eid, 0.0)
            new_conf = float(rel.get("confidence", 0.5))
            if new_conf > current:
                fact_eid_to_conf[fact_eid] = new_conf

        if not fact_eid_to_sf_eids:
            # No relations yet — still useful as SF-only node set
            logger.info(
                "build_physiological_graph — no fact_sf_relations; "
                "graph has %d SF nodes, 0 taxon nodes, 0 edges",
                len(sf_node_docs),
            )
            return {
                "nodes": len(sf_node_docs), "edges": 0,
                "sf_nodes": len(sf_node_docs), "taxon_nodes": 0,
                "exhibited_by_edges": 0,
            }

        # Step 2b: fact_id → document_id via facts collection
        all_fact_oids = [ObjectId(feid) for feid in fact_eid_to_sf_eids if ObjectId.is_valid(feid)]
        fact_eid_to_doc_eid: Dict[str, str] = {}
        async for fact in self.db.facts.find(
            {"_id": {"$in": all_fact_oids}},
            {"_id": 1, "document_id": 1},
        ):
            fact_eid_to_doc_eid[str(fact["_id"])] = str(fact.get("document_id", ""))

        # Step 2c: document_id → set(tax_id) via document_taxon_relations
        all_doc_eids_needed = set(fact_eid_to_doc_eid.values()) - {""}
        doc_eid_to_taxids: Dict[str, Dict[int, float]] = {}  # doc_eid → tax_id → max_conf

        if all_doc_eids_needed:
            from bson import ObjectId as _OID
            doc_oids = [_OID(d) for d in all_doc_eids_needed if _OID.is_valid(d)]

            # Optional subtree filter
            taxid_query: Dict[str, Any] = {"status": {"$in": ["suggested", "confirmed"]}}
            if root_taxid is not None:
                # Collect tax_ids in the subtree first (compact in-memory filter)
                subtree_taxids: List[int] = []
                async for t in self.db.taxonomy_nodes.find(
                    {"$or": [{"tax_id": root_taxid}, {"lineage": root_taxid}]},
                    {"tax_id": 1},
                ):
                    subtree_taxids.append(t["tax_id"])
                if subtree_taxids:
                    taxid_query["tax_id"] = {"$in": subtree_taxids}

            taxid_query["document_id"] = {"$in": doc_oids}

            async for dtr in self.db.document_taxon_relations.find(
                taxid_query,
                {"document_id": 1, "tax_id": 1, "confidence": 1},
            ):
                deid = str(dtr["document_id"])
                tid = dtr["tax_id"]
                conf = float(dtr.get("confidence", 0.5))
                inner = doc_eid_to_taxids.setdefault(deid, {})
                if conf > inner.get(tid, 0.0):
                    inner[tid] = conf

        # Step 2d: build sf_eid → {tax_id: max_edge_weight}
        # Edge weight = product of max(fact→sf confidence) × max(doc→taxon confidence)
        sf_taxid_weight: Dict[str, Dict[int, float]] = {}

        for fact_eid, sf_eids in fact_eid_to_sf_eids.items():
            doc_eid = fact_eid_to_doc_eid.get(fact_eid, "")
            if not doc_eid:
                continue
            taxid_confs = doc_eid_to_taxids.get(doc_eid, {})
            if not taxid_confs:
                continue
            fact_conf = fact_eid_to_conf.get(fact_eid, 0.5)
            for sf_eid in sf_eids:
                if sf_eid not in sf_entity_to_node:
                    continue
                for tax_id, taxon_conf in taxid_confs.items():
                    weight = round(fact_conf * taxon_conf, 4)
                    inner = sf_taxid_weight.setdefault(sf_eid, {})
                    if weight > inner.get(tax_id, 0.0):
                        inner[tax_id] = weight

        if not sf_taxid_weight:
            logger.info(
                "build_physiological_graph — no exhibited_by paths found; "
                "%d SF nodes, 0 taxon nodes",
                len(sf_node_docs),
            )
            return {
                "nodes": len(sf_node_docs), "edges": 0,
                "sf_nodes": len(sf_node_docs), "taxon_nodes": 0,
                "exhibited_by_edges": 0,
            }

        # ---- 3. Collect and insert taxon nodes ----
        needed_taxids: set = set()
        for tid_map in sf_taxid_weight.values():
            needed_taxids.update(tid_map.keys())

        taxid_to_node_id: Dict[int, ObjectId] = {}
        taxon_node_docs: List[Dict[str, Any]] = []
        async for taxon in self.db.taxonomy_nodes.find(
            {"tax_id": {"$in": list(needed_taxids)}},
        ):
            taxon_node_docs.append({
                "schema_id": schema_id,
                "node_type": "taxon",
                "entity_collection": "taxonomy_nodes",
                "entity_id": str(taxon["_id"]),
                "label": taxon.get("name", str(taxon.get("tax_id", ""))),
                "properties": {
                    "rank": taxon.get("rank", ""),
                    "tax_id": taxon.get("tax_id"),
                    "cluster_id": f"rank:{taxon.get('rank', 'unknown')}",
                },
                "_tax_id": taxon.get("tax_id"),
            })

        if taxon_node_docs:
            result = await self.nodes.insert_many(taxon_node_docs)
            for i, nd in enumerate(taxon_node_docs):
                taxid_to_node_id[nd["_tax_id"]] = result.inserted_ids[i]
            await self.nodes.update_many(
                {"schema_id": schema_id, "node_type": "taxon"},
                {"$unset": {"_tax_id": ""}},
            )

        logger.info("build_physiological_graph — %d taxon nodes", len(taxon_node_docs))

        # ---- 4. Insert exhibited_by edges ----
        exhibited_edge_docs: List[Dict[str, Any]] = []
        for sf_eid, tid_map in sf_taxid_weight.items():
            if sf_eid not in sf_entity_to_node:
                continue
            sf_node_id = sf_entity_to_node[sf_eid]
            for tax_id, weight in tid_map.items():
                if tax_id not in taxid_to_node_id:
                    continue
                exhibited_edge_docs.append({
                    "schema_id": schema_id,
                    "edge_type": "exhibited_by",
                    "source_node_id": sf_node_id,
                    "target_node_id": taxid_to_node_id[tax_id],
                    "weight": weight,
                    "properties": {},
                })

        if exhibited_edge_docs:
            await self.edges.insert_many(exhibited_edge_docs)

        total_nodes = len(sf_node_docs) + len(taxon_node_docs)
        total_edges = len(exhibited_edge_docs)

        logger.info(
            "build_physiological_graph complete — "
            "%d sf_nodes, %d taxon_nodes, %d exhibited_by edges",
            len(sf_node_docs), len(taxon_node_docs), total_edges,
        )
        return {
            "nodes": total_nodes,
            "edges": total_edges,
            "sf_nodes": len(sf_node_docs),
            "taxon_nodes": len(taxon_node_docs),
            "exhibited_by_edges": total_edges,
        }
