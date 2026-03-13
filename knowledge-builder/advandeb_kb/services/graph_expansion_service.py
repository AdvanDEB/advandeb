"""
GraphExpansionService — AQL-based graph traversal and context expansion.

Given seed chunk IDs from vector/hybrid retrieval, this service:
  1. Expands context by traversing ArangoDB named graphs
  2. Extracts citation chains (document provenance)
  3. Finds related facts and stylized facts
  4. Builds provenance traces for storage

All operations are synchronous (python-arango is sync).
Use run_in_executor when calling from async contexts.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from advandeb_kb.database.arango_client import ArangoDatabase
from advandeb_kb.models.provenance import GraphPathStep, ProvenanceTrace

logger = logging.getLogger(__name__)


class GraphExpansionService:
    """
    Traverses ArangoDB named graphs starting from retrieved chunks to
    expand retrieval context and build provenance traces.

    Args:
        arango_db: Connected ArangoDatabase instance.
    """

    def __init__(self, arango_db: ArangoDatabase):
        self.db = arango_db

    # ------------------------------------------------------------------
    # Core context expansion
    # ------------------------------------------------------------------

    def expand_from_chunks(
        self,
        chunk_ids: list[str],
        max_hops: int = 2,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Expand retrieval context by traversing from seed chunks outward.

        Traverses:  chunk → document → facts → stylized_facts → taxa

        Args:
            chunk_ids:  List of ChromaDB chunk IDs (format: "{doc_id}_chunk_{i}")
            max_hops:   Maximum traversal depth (default 2).
            limit:      Maximum vertices to return per traversal.

        Returns:
            {
                "chunks":         list of chunk docs,
                "documents":      list of parent document docs,
                "facts":          list of related fact docs,
                "stylized_facts": list of related SF docs,
                "taxa":           list of related taxon docs,
                "graph_path":     list of GraphPathStep dicts,
            }
        """
        result: dict[str, Any] = {
            "chunks": [],
            "documents": [],
            "facts": [],
            "stylized_facts": [],
            "taxa": [],
            "graph_path": [],
        }

        if not chunk_ids:
            return result

        # 1. Resolve chunk keys → ArangoDB vertex IDs
        chunk_keys = self._chunk_ids_to_arango_keys(chunk_ids)
        if not chunk_keys:
            logger.debug("expand_from_chunks: no arango chunk keys found for %s", chunk_ids[:3])
            return result

        # 2. Fetch chunk documents themselves
        result["chunks"] = self._fetch_vertices("chunks", chunk_keys)

        # 3. For each chunk, get parent document IDs
        doc_ids = list({c.get("document_id", "") for c in result["chunks"] if c.get("document_id")})
        if doc_ids:
            result["documents"] = self._fetch_by_field("documents", "mongo_id", doc_ids)

        # 4. Traverse chunk_graph: chunk → document
        chunk_arango_ids = [f"chunks/{k}" for k in chunk_keys]
        chunk_graph_expansion = self._traverse_graph(
            start_ids=chunk_arango_ids,
            graph_name="chunk_graph",
            direction="OUTBOUND",
            min_depth=1,
            max_depth=1,
            limit=limit,
        )
        result["graph_path"].extend(chunk_graph_expansion["path_steps"])

        # 5. Traverse support_graph from fact → stylized_fact
        #    First get facts linked to these documents via AQL
        if doc_ids:
            doc_arango_ids = self._doc_mongo_ids_to_arango(doc_ids)
            facts = self._get_facts_for_documents(doc_ids)
            result["facts"] = facts

            fact_arango_ids = [f"facts/{f.get('_key', f.get('chunk_id',''))}" for f in facts if f.get("_key")]
            if fact_arango_ids:
                support_expansion = self._traverse_graph(
                    start_ids=fact_arango_ids,
                    graph_name="support_graph",
                    direction="OUTBOUND",
                    min_depth=1,
                    max_depth=1,
                    limit=limit,
                )
                result["stylized_facts"] = support_expansion["vertices"]
                result["graph_path"].extend(support_expansion["path_steps"])

        # 6. Traverse knowledge_graph from documents → taxa
        if doc_ids:
            kg_expansion = self._traverse_graph(
                start_ids=self._doc_mongo_ids_to_arango(doc_ids),
                graph_name="knowledge_graph",
                direction="OUTBOUND",
                min_depth=1,
                max_depth=max_hops,
                limit=limit,
            )
            result["taxa"] = [
                v for v in kg_expansion["vertices"]
                if v.get("_id", "").startswith("taxa/")
            ]
            result["graph_path"].extend(kg_expansion["path_steps"])

        logger.debug(
            "expand_from_chunks: %d chunks → %d docs, %d facts, %d SFs, %d taxa, %d path steps",
            len(chunk_ids),
            len(result["documents"]),
            len(result["facts"]),
            len(result["stylized_facts"]),
            len(result["taxa"]),
            len(result["graph_path"]),
        )
        return result

    # ------------------------------------------------------------------
    # Citation chain extraction
    # ------------------------------------------------------------------

    def get_citation_chain(
        self, document_id: str, max_depth: int = 5
    ) -> list[dict[str, Any]]:
        """
        Walk the citation graph outward from a document.

        Returns an ordered list of citation hops:
            [{"document": {...}, "edge": {"relation": "cites"}}, ...]
        """
        aql = """
        FOR v, e IN 1..@max_depth OUTBOUND @start_id
            GRAPH 'citation_graph'
            OPTIONS {uniqueVertices: 'global', bfsMode: true}
            RETURN {
                document: v,
                edge: {
                    _from: e._from,
                    _to: e._to,
                    relation: 'cites'
                }
            }
        """
        # Try to find the document by its Mongo ID stored as a field
        start_candidates = self._doc_mongo_ids_to_arango([document_id])
        if not start_candidates:
            return []

        try:
            rows = self.db.aql(
                aql,
                bind_vars={"start_id": start_candidates[0], "max_depth": max_depth},
            )
            return rows
        except Exception as exc:
            logger.warning("get_citation_chain failed for %s: %s", document_id, exc)
            return []

    def get_citation_chain_mongo(
        self, document_id: str, max_depth: int = 5
    ) -> list[dict[str, Any]]:
        """
        MongoDB-based citation chain: follows `cited_by` or `references`
        arrays if present (no ArangoDB required).
        """
        # Placeholder — real implementation reads from MongoDB documents.references[]
        # and recursively follows up to max_depth levels.
        # Used when ArangoDB citation_graph hasn't been populated yet.
        return []

    # ------------------------------------------------------------------
    # Related facts / SFs for a query (no seed chunks needed)
    # ------------------------------------------------------------------

    def find_related_facts(
        self, stylized_fact_id: str, direction: str = "INBOUND", limit: int = 20
    ) -> list[dict[str, Any]]:
        """
        Find facts that support or oppose a stylized fact.

        Args:
            stylized_fact_id: ArangoDB key (or Mongo ID) of the stylized fact.
            direction: INBOUND = facts→SF (default), OUTBOUND = SF→facts (unusual).
        """
        sf_arango_id = f"stylized_facts/{stylized_fact_id}"
        aql = f"""
        FOR v, e IN 1..1 {direction} @sf_id
            GRAPH 'support_graph'
            RETURN {{
                fact: v,
                relation: e.relation_type,
                confidence: e.confidence
            }}
        """
        try:
            return self.db.aql(aql, bind_vars={"sf_id": sf_arango_id})[:limit]
        except Exception as exc:
            logger.warning("find_related_facts failed: %s", exc)
            return []

    def find_taxa_for_document(self, document_id: str) -> list[dict[str, Any]]:
        """
        Return taxa linked to a document via the knowledge_graph edges.
        """
        arango_ids = self._doc_mongo_ids_to_arango([document_id])
        if not arango_ids:
            return []
        aql = """
        FOR v, e IN 1..1 OUTBOUND @doc_id
            GRAPH 'knowledge_graph'
            FILTER STARTS_WITH(v._id, 'taxa/')
            RETURN {
                taxon: v,
                confidence: e.confidence,
                evidence: e.evidence,
                status: e.status
            }
        """
        try:
            return self.db.aql(aql, bind_vars={"doc_id": arango_ids[0]})
        except Exception as exc:
            logger.warning("find_taxa_for_document failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Provenance trace builder
    # ------------------------------------------------------------------

    def build_provenance_trace(
        self,
        query: str,
        chunk_ids: list[str],
        expansion: dict[str, Any],
        session_id: Optional[str] = None,
        confidence_score: float = 0.0,
    ) -> ProvenanceTrace:
        """
        Build a ProvenanceTrace from retrieval results and graph expansion.
        """
        documents_cited = [
            str(d.get("_key") or d.get("_id", ""))
            for d in expansion.get("documents", [])
        ]
        facts_used = [
            str(f.get("_key") or f.get("_id", ""))
            for f in expansion.get("facts", [])
        ]
        graph_path = [
            GraphPathStep(**step)
            for step in expansion.get("graph_path", [])
            if isinstance(step, dict) and "from_id" in step
        ]

        return ProvenanceTrace(
            session_id=session_id,
            query=query,
            facts_used=facts_used,
            chunks_retrieved=chunk_ids,
            documents_cited=documents_cited,
            graph_path=graph_path,
            confidence_score=confidence_score,
            retrieval_methods=["vector", "graph"],
        )

    def store_provenance_trace(self, trace: ProvenanceTrace) -> str:
        """
        Persist a ProvenanceTrace in the ArangoDB provenance_traces collection.
        Returns the ArangoDB _key of the inserted document.
        """
        doc = trace.model_dump(by_alias=True, mode="json")
        # Convert any ObjectId to string for ArangoDB
        doc["_key"] = str(doc.pop("_id", ""))
        meta = self.db.insert("provenance_traces", doc)
        return meta["_key"]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _chunk_ids_to_arango_keys(self, chunk_ids: list[str]) -> list[str]:
        """
        Query ArangoDB chunks collection to find keys matching given chunk_ids.
        chunk_id format stored in Arango: "{doc_id}_chunk_{index}"
        """
        if not chunk_ids:
            return []
        aql = """
        FOR c IN chunks
            FILTER c.chunk_id IN @ids
            RETURN c._key
        """
        try:
            return self.db.aql(aql, bind_vars={"ids": chunk_ids})
        except Exception as exc:
            logger.warning("_chunk_ids_to_arango_keys failed: %s", exc)
            return []

    def _fetch_vertices(self, collection: str, keys: list[str]) -> list[dict]:
        if not keys:
            return []
        aql = """
        FOR doc IN @@col
            FILTER doc._key IN @keys
            RETURN doc
        """
        try:
            return self.db.aql(aql, bind_vars={"@col": collection, "keys": keys})
        except Exception as exc:
            logger.warning("_fetch_vertices %s failed: %s", collection, exc)
            return []

    def _fetch_by_field(
        self, collection: str, field: str, values: list[str]
    ) -> list[dict]:
        aql = """
        FOR doc IN @@col
            FILTER doc[@field] IN @values
            RETURN doc
        """
        try:
            return self.db.aql(
                aql,
                bind_vars={"@col": collection, "field": field, "values": values},
            )
        except Exception as exc:
            logger.warning("_fetch_by_field %s.%s failed: %s", collection, field, exc)
            return []

    def _doc_mongo_ids_to_arango(self, mongo_ids: list[str]) -> list[str]:
        """
        Resolve MongoDB ObjectId strings → ArangoDB vertex IDs.
        ArangoDB _key == mongo_id (set during migration).
        """
        return [f"documents/{mid}" for mid in mongo_ids if mid]

    def _get_facts_for_documents(self, doc_mongo_ids: list[str]) -> list[dict]:
        aql = """
        FOR f IN facts
            FILTER f.document_id IN @doc_ids
            RETURN f
        """
        try:
            return self.db.aql(aql, bind_vars={"doc_ids": doc_mongo_ids})
        except Exception as exc:
            logger.warning("_get_facts_for_documents failed: %s", exc)
            return []

    def _traverse_graph(
        self,
        start_ids: list[str],
        graph_name: str,
        direction: str = "ANY",
        min_depth: int = 1,
        max_depth: int = 2,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Run AQL graph traversal from multiple starting vertices.

        Returns:
            {"vertices": [...], "path_steps": [GraphPathStep dicts]}
        """
        if not start_ids:
            return {"vertices": [], "path_steps": []}

        vertices: list[dict] = []
        path_steps: list[dict] = []
        seen: set[str] = set()

        for start_id in start_ids:
            aql = f"""
            FOR v, e IN {min_depth}..{max_depth} {direction} @start
                GRAPH @graph
                OPTIONS {{uniqueVertices: 'global', bfsMode: true}}
                LIMIT @limit
                RETURN {{vertex: v, edge: e}}
            """
            try:
                rows = self.db.aql(
                    aql,
                    bind_vars={
                        "start": start_id,
                        "graph": graph_name,
                        "limit": limit,
                    },
                )
                for row in rows:
                    v = row.get("vertex") or {}
                    e = row.get("edge") or {}
                    vid = v.get("_id", "")
                    if vid and vid not in seen:
                        seen.add(vid)
                        vertices.append(v)
                    if e.get("_from") and e.get("_to"):
                        path_steps.append({
                            "from_id": e["_from"],
                            "to_id": e["_to"],
                            "edge_type": e.get("_id", "").split("/")[0] if e.get("_id") else graph_name,
                            "edge_attrs": {
                                k: v for k, v in e.items()
                                if k not in ("_id", "_key", "_rev", "_from", "_to")
                            },
                        })
            except Exception as exc:
                logger.warning(
                    "_traverse_graph %s from %s failed: %s", graph_name, start_id, exc
                )

        return {"vertices": vertices, "path_steps": path_steps}
