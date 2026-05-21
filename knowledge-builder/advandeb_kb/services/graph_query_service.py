"""
GraphQueryService — live ArangoDB graph queries for visualization.

Replaces the old VisualizationService + GraphBuilderService pair.

Design
------
* No materialization — all graph data is fetched on-demand from ArangoDB
  edge collections and vertex collections via AQL.
* No graph_schemas / graph_nodes / graph_edges MongoDB collections needed.
* Schema definitions are static (BUILTIN_SCHEMAS from models/graph.py).
* Layout computation (NetworkX) happens on-demand, in a thread executor,
  and the results are returned directly to the caller — they are NOT
  persisted (no storage needed; layouts are cheap enough for the data
  sizes we serve).

Schema → ArangoDB mapping
--------------------------
  citation              → edge coll: citations          verts: documents
  sf_support            → edge coll: sf_support         verts: documents, facts, stylized_facts
  taxonomical           → edge coll: taxonomical        verts: taxa
  knowledge_graph       → named graph: knowledge_graph  (all verts)
  physiological_process → edge colls: sf_support + knowledge_graph  verts: stylized_facts, taxa
  chatbot               → app MongoDB: chat_sessions/messages + ArangoDB KB

All operations that call self.db (python-arango, synchronous) are wrapped in
run_in_executor so they are safe to call from async FastAPI handlers.

Usage
-----
    from advandeb_kb.services.graph_query_service import GraphQueryService
    svc = GraphQueryService(arango_db, app_mongo_db=app_db)
    schemas = svc.list_schemas()
    data    = await svc.get_graph_data("sf_support", limit=2000)
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import networkx as nx

from advandeb_kb.database.arango_client import ArangoDatabase
from advandeb_kb.models.graph import BUILTIN_SCHEMAS

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gqs")

# ---------------------------------------------------------------------------
# ArangoDB collection/graph mapping per schema name
# ---------------------------------------------------------------------------

# Each schema entry describes how to fetch nodes and edges from ArangoDB.
# "named_graph" = use FOR v,e IN ... GRAPH <name> traversal
# "edge_colls"  = raw edge collection names
# "vertex_colls"= vertex collections to load for the schema
_SCHEMA_ARANGO: Dict[str, Dict[str, Any]] = {
    "citation": {
        "vertex_colls": ["documents"],
        "edge_colls": ["citations"],
        "named_graph": None,
    },
    "sf_support": {
        "vertex_colls": ["documents", "facts", "stylized_facts"],
        "edge_colls": ["sf_support"],
        # Also need to load fact→document edges (facts.document_id field, not an edge coll)
        "extra": "fact_doc_link",
        "named_graph": None,
    },
    "taxonomical": {
        "vertex_colls": ["taxa"],
        "edge_colls": ["taxonomical"],
        "named_graph": None,
    },
    "knowledge_graph": {
        "vertex_colls": ["documents", "facts", "stylized_facts", "taxa"],
        "edge_colls": ["citations", "sf_support", "knowledge_graph"],
        "named_graph": None,
    },
    "physiological_process": {
        "vertex_colls": ["stylized_facts", "taxa"],
        "edge_colls": ["sf_support", "knowledge_graph"],
        "named_graph": None,
    },
    "chatbot": {
        # Special: requires app MongoDB for chat data.
        # Handled separately in _fetch_chatbot_graph().
        "vertex_colls": [],
        "edge_colls": [],
        "named_graph": None,
    },
}

# ---------------------------------------------------------------------------
# Node / edge serializers (produce plain JSON-serializable dicts)
# ---------------------------------------------------------------------------

def _serialize_vertex(doc: Dict[str, Any], node_type: str) -> Dict[str, Any]:
    """Convert an ArangoDB vertex document to a graph node dict."""
    key = doc.get("_key", "")
    return {
        "_id": key,
        "label": _get_label(doc, node_type),
        "node_type": node_type,
        "entity_collection": _node_type_to_collection(node_type),
        "entity_id": key,
        "cluster_id": _get_cluster_id(doc, node_type),
        "degree": 0,
        "properties": _extract_properties(doc, node_type),
        "x": None, "y": None, "z": None, "x2d": None, "y2d": None,
    }


def _serialize_edge(e_from: str, e_to: str, edge_type: str,
                    weight: float = 1.0, edge_key: str = "") -> Dict[str, Any]:
    """Convert ArangoDB edge _from/_to to a graph edge dict."""
    # _from / _to are "collection/key" — we want just the key part as node id
    src = e_from.split("/")[-1] if "/" in e_from else e_from
    tgt = e_to.split("/")[-1] if "/" in e_to else e_to
    return {
        "_id": edge_key or f"{src}_{tgt}",
        "source_node_id": src,
        "target_node_id": tgt,
        "edge_type": edge_type,
        "weight": weight,
        "properties": {},
    }


def _node_type_to_collection(node_type: str) -> str:
    mapping = {
        "document": "documents",
        "fact": "facts",
        "stylized_fact": "stylized_facts",
        "taxon": "taxa",
        "user": "users",
        "chat_session": "chat_sessions",
    }
    return mapping.get(node_type, node_type)


def _get_label(doc: Dict[str, Any], node_type: str) -> str:
    if node_type == "document":
        return doc.get("title", doc.get("_key", ""))
    if node_type == "fact":
        return doc.get("content", doc.get("_key", ""))
    if node_type == "stylized_fact":
        return doc.get("statement", doc.get("_key", ""))
    if node_type == "taxon":
        return doc.get("name", str(doc.get("tax_id", doc.get("_key", ""))))
    if node_type == "user":
        return doc.get("user_id", doc.get("_key", ""))
    if node_type == "chat_session":
        return doc.get("title", doc.get("_key", ""))
    return doc.get("_key", "")


def _get_cluster_id(doc: Dict[str, Any], node_type: str) -> str:
    if node_type == "document":
        return f"doc:{doc.get('general_domain', 'unknown')}"
    if node_type == "fact":
        return "fact"
    if node_type == "stylized_fact":
        return f"sf:{doc.get('category', 'uncategorized')}"
    if node_type == "taxon":
        return f"taxon:{doc.get('rank', 'unknown')}"
    return node_type


def _extract_properties(doc: Dict[str, Any], node_type: str) -> Dict[str, Any]:
    """Extract the relevant properties subset for each node type."""
    if node_type == "document":
        return {k: doc.get(k) for k in ("doi", "year", "authors", "journal", "general_domain")}
    if node_type == "fact":
        return {k: doc.get(k) for k in ("confidence", "status", "entities", "document_id")}
    if node_type == "stylized_fact":
        return {k: doc.get(k) for k in ("category", "status", "sf_number")}
    if node_type == "taxon":
        return {k: doc.get(k) for k in ("rank", "tax_id", "gbif_usage_key", "common_names")}
    if node_type == "user":
        return {"user_id": doc.get("user_id")}
    if node_type == "chat_session":
        return {k: doc.get(k) for k in ("user_id", "created_at")}
    return {}


def _aql_limit(bind_name: str, limit: Optional[int]) -> tuple[str, Dict[str, Any]]:
    if limit is None:
        return "", {}
    return f"LIMIT @{bind_name}", {bind_name: limit}


# ---------------------------------------------------------------------------
# Compute degree for nodes from edges
# ---------------------------------------------------------------------------

def _compute_degrees(nodes: List[Dict], edges: List[Dict]) -> None:
    """Add 'degree' field to each node dict in-place."""
    deg: Dict[str, int] = {}
    for e in edges:
        src = e.get("source_node_id", "")
        tgt = e.get("target_node_id", "")
        deg[src] = deg.get(src, 0) + 1
        deg[tgt] = deg.get(tgt, 0) + 1
    for n in nodes:
        n["degree"] = deg.get(n["_id"], 0)


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class GraphQueryService:
    """
    Live ArangoDB graph query service — no materialized collections.

    Args:
        arango_db:   Connected ArangoDatabase instance (synchronous python-arango).
        app_mongo_db: AsyncIOMotorDatabase for the app DB (chat_sessions/messages).
                      Required only for the "chatbot" schema; may be None otherwise.
    """

    def __init__(
        self,
        arango_db: ArangoDatabase,
        app_mongo_db: Any = None,
    ):
        self.db = arango_db
        self.app_db = app_mongo_db  # async Motor db for chat data

    # ------------------------------------------------------------------
    # Schema listing (static — from BUILTIN_SCHEMAS)
    # ------------------------------------------------------------------

    def list_schemas(self) -> List[Dict[str, Any]]:
        """Return all built-in schema definitions as plain dicts."""
        results = []
        for i, schema in enumerate(BUILTIN_SCHEMAS):
            results.append({
                "_id": schema["name"],   # use name as stable ID (no MongoDB ObjectId)
                "name": schema["name"],
                "description": schema.get("description", ""),
                "is_builtin": schema.get("is_builtin", True),
                "node_types": schema.get("node_types", []),
                "edge_types": schema.get("edge_types", []),
            })
        return results

    def get_schema_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Return a single schema definition by name."""
        for s in self.list_schemas():
            if s["name"] == name:
                return s
        return None

    # ------------------------------------------------------------------
    # Core graph data fetch (async entry point — uses run_in_executor)
    # ------------------------------------------------------------------

    async def get_graph_data(
        self,
        schema_name: str,
        limit: Optional[int] = 2000,
    ) -> Dict[str, Any]:
        """Return {"nodes": [...], "edges": [...]} for a schema.

        All data is fetched fresh from ArangoDB (no cache).
        """
        loop = asyncio.get_running_loop()
        if schema_name == "chatbot":
            return await self._fetch_chatbot_graph(limit=limit)
        return await loop.run_in_executor(
            _executor,
            self._fetch_graph_sync,
            schema_name,
            limit,
        )

    async def get_graph_with_layout(
        self,
        schema_name: str,
        layout: str = "force",
        limit: Optional[int] = 2000,
    ) -> Dict[str, Any]:
        """Same as get_graph_data but adds x/y/z/x2d/y2d layout coordinates."""
        data = await self.get_graph_data(schema_name, limit=limit)
        nodes = data["nodes"]
        edges = data["edges"]
        if not nodes:
            return {"nodes": [], "edges": [], "schema": schema_name, "layout": layout}

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            _executor,
            _apply_layout,
            nodes,
            edges,
            schema_name,
        )
        return {"nodes": nodes, "edges": edges, "schema": schema_name, "layout": layout}

    # ------------------------------------------------------------------
    # On-demand loading helpers (async)
    # ------------------------------------------------------------------

    async def get_overview(
        self,
        schema_name: str,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Return top-`limit` nodes by degree, plus internal edges and layout."""
        data = await self.get_graph_data(schema_name, limit=10_000)
        nodes = data["nodes"]
        edges = data["edges"]
        _compute_degrees(nodes, edges)
        nodes_sorted = sorted(nodes, key=lambda n: n.get("degree", 0), reverse=True)[:limit]
        top_ids = {n["_id"] for n in nodes_sorted}
        top_edges = [
            e for e in edges
            if e["source_node_id"] in top_ids and e["target_node_id"] in top_ids
        ]

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            _executor,
            _apply_layout,
            nodes_sorted,
            top_edges,
            schema_name,
        )

        return {"nodes": nodes_sorted, "edges": top_edges}

    async def get_all_edges(self, schema_name: str) -> List[Dict[str, Any]]:
        """Return every edge for the schema."""
        data = await self.get_graph_data(schema_name, limit=50_000)
        return data["edges"]

    async def expand_node(
        self,
        schema_name: str,
        node_id: str,
        loaded_node_ids: List[str],
    ) -> Dict[str, Any]:
        """Return 1-hop neighbors of node_id not already in loaded_node_ids.

        Fetches the full graph then filters in Python — fine for our data sizes.
        """
        data = await self.get_graph_data(schema_name, limit=50_000)
        all_nodes = {n["_id"]: n for n in data["nodes"]}
        all_edges = data["edges"]
        loaded_set = set(loaded_node_ids) | {node_id}

        neighbor_ids: set = set()
        for e in all_edges:
            src, tgt = e["source_node_id"], e["target_node_id"]
            if src == node_id:
                neighbor_ids.add(tgt)
            elif tgt == node_id:
                neighbor_ids.add(src)

        new_ids = neighbor_ids - loaded_set
        new_nodes = [all_nodes[nid] for nid in new_ids if nid in all_nodes]
        all_relevant = new_ids | loaded_set
        new_edges = [
            e for e in all_edges
            if e["source_node_id"] in all_relevant and e["target_node_id"] in all_relevant
            and (e["source_node_id"] in new_ids or e["target_node_id"] in new_ids)
        ]
        return {"nodes": new_nodes, "edges": new_edges}

    async def get_type_nodes(
        self,
        schema_name: str,
        node_type: str,
        loaded_node_ids: List[str],
    ) -> Dict[str, Any]:
        """Return all nodes of node_type not already in loaded_node_ids."""
        data = await self.get_graph_data(schema_name, limit=50_000)
        loaded_set = set(loaded_node_ids)
        new_nodes = [
            n for n in data["nodes"]
            if n["node_type"] == node_type and n["_id"] not in loaded_set
        ]
        new_ids = {n["_id"] for n in new_nodes}
        all_relevant = new_ids | loaded_set
        new_edges = [
            e for e in data["edges"]
            if e["source_node_id"] in all_relevant and e["target_node_id"] in all_relevant
            and (e["source_node_id"] in new_ids or e["target_node_id"] in new_ids)
        ]
        return {"nodes": new_nodes, "edges": new_edges}

    async def get_type_nodes_paged(
        self,
        schema_name: str,
        node_type: str,
        page: int = 0,
        page_size: int = 500,
    ) -> Dict[str, Any]:
        """Return a paginated slice of nodes of node_type."""
        data = await self.get_graph_data(schema_name, limit=50_000)
        type_nodes = [n for n in data["nodes"] if n["node_type"] == node_type]
        total = len(type_nodes)
        start = page * page_size
        sliced = type_nodes[start: start + page_size]
        return {
            "nodes": sliced,
            "edges": [],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": (start + page_size) < total,
        }

    async def get_type_counts(self, schema_name: str) -> Dict[str, Any]:
        """Return {node_type: count} and {edge_type: count} for a schema."""
        data = await self.get_graph_data(schema_name, limit=50_000)
        node_types: Dict[str, int] = {}
        edge_types: Dict[str, int] = {}
        for n in data["nodes"]:
            nt = n.get("node_type", "default")
            node_types[nt] = node_types.get(nt, 0) + 1
        for e in data["edges"]:
            et = e.get("edge_type", "default")
            edge_types[et] = edge_types.get(et, 0) + 1
        return {"node_types": node_types, "edge_types": edge_types}

    async def get_stats(self, schema_name: str) -> Dict[str, Any]:
        """Return node count, edge count, density for a schema."""
        data = await self.get_graph_data(schema_name, limit=50_000)
        nc = len(data["nodes"])
        ec = len(data["edges"])
        density = 0.0
        if nc > 1:
            max_edges = nc * (nc - 1)
            density = ec / max_edges if max_edges else 0.0
        return {"node_count": nc, "edge_count": ec, "density": density}

    # ------------------------------------------------------------------
    # Streaming helper (for SSE endpoint)
    # ------------------------------------------------------------------

    async def iter_graph_stream(
        self,
        schema_name: str,
        limit: int = 5000,
        batch_size: int = 200,
    ):
        """Async generator: yields (event_type, payload_dict) tuples.

        event_type is one of: "nodes", "edges", "done", "error"
        """
        try:
            data = await self.get_graph_data(schema_name, limit=limit)
        except Exception as exc:
            logger.exception("iter_graph_stream schema=%s failed", schema_name)
            yield "error", {"detail": str(exc)}
            return

        nodes = data["nodes"]
        edges = data["edges"]
        emitted_ids: set = set()

        # Stream nodes in batches
        total_batches = max(1, -(-len(nodes) // batch_size))
        batch_idx = 0
        batch: list = []
        for node in nodes:
            emitted_ids.add(node["_id"])
            batch.append(node)
            if len(batch) >= batch_size:
                yield "nodes", {
                    "nodes": batch,
                    "batch": batch_idx,
                    "total_batches": total_batches,
                }
                batch = []
                batch_idx += 1
                await asyncio.sleep(0)

        if batch:
            yield "nodes", {
                "nodes": batch,
                "batch": batch_idx,
                "total_batches": total_batches,
            }
            await asyncio.sleep(0)

        # Stream edges whose both endpoints were emitted
        edge_batch: list = []
        edge_count = 0
        for edge in edges:
            if (edge["source_node_id"] in emitted_ids
                    and edge["target_node_id"] in emitted_ids):
                edge_batch.append(edge)
                edge_count += 1
                if len(edge_batch) >= batch_size * 2:
                    yield "edges", {"edges": edge_batch}
                    edge_batch = []
                    await asyncio.sleep(0)

        if edge_batch:
            yield "edges", {"edges": edge_batch}

        yield "done", {"node_count": len(emitted_ids), "edge_count": edge_count}

    # ------------------------------------------------------------------
    # Synchronous ArangoDB fetch (called via run_in_executor)
    # ------------------------------------------------------------------

    def _fetch_graph_sync(
        self,
        schema_name: str,
        limit: Optional[int],
    ) -> Dict[str, Any]:
        """Blocking fetch — called in a thread executor."""
        cfg = _SCHEMA_ARANGO.get(schema_name)
        if cfg is None:
            logger.warning("_fetch_graph_sync: unknown schema %r", schema_name)
            return {"nodes": [], "edges": []}

        if schema_name == "citation":
            return self._fetch_citation(limit)
        if schema_name == "sf_support":
            return self._fetch_sf_support(limit)
        if schema_name == "taxonomical":
            return self._fetch_taxonomical(limit)
        if schema_name == "knowledge_graph":
            return self._fetch_knowledge_graph(limit)
        if schema_name == "physiological_process":
            return self._fetch_physiological(limit)
        return {"nodes": [], "edges": []}

    # ------------------------------------------------------------------
    # Per-schema fetch implementations (synchronous)
    # ------------------------------------------------------------------

    def _fetch_citation(self, limit: Optional[int]) -> Dict[str, Any]:
        """Fetch citation graph: document nodes + cites edges."""
        doc_limit_clause, doc_bind = _aql_limit("limit", limit)
        edge_limit_clause, edge_bind = _aql_limit("edge_limit", None if limit is None else limit * 2)
        # Get documents that appear in at least one citation edge
        aql_docs = f"""
        LET cited_keys = (
            FOR e IN citations
                RETURN DISTINCT PARSE_IDENTIFIER(e._from).key
        )
        LET citing_keys = (
            FOR e IN citations
                RETURN DISTINCT PARSE_IDENTIFIER(e._to).key
        )
        FOR d IN documents
            FILTER d._key IN cited_keys OR d._key IN citing_keys
            {doc_limit_clause}
            RETURN d
        """
        aql_edges = f"""
        FOR e IN citations
            {edge_limit_clause}
            RETURN {{_from: e._from, _to: e._to, _key: e._key,
                    weight: e.weight || 1.0}}
        """
        docs = self._aql(aql_docs, doc_bind)
        nodes = [_serialize_vertex(d, "document") for d in docs]
        node_keys = {n["_id"] for n in nodes}

        raw_edges = self._aql(aql_edges, edge_bind)
        edges = []
        for e in raw_edges:
            se = _serialize_edge(e["_from"], e["_to"], "cites",
                                 float(e.get("weight", 1.0)), e.get("_key", ""))
            if se["source_node_id"] in node_keys and se["target_node_id"] in node_keys:
                edges.append(se)

        _compute_degrees(nodes, edges)
        return {"nodes": nodes, "edges": edges}

    def _fetch_sf_support(self, limit: Optional[int]) -> Dict[str, Any]:
        """Fetch sf_support graph: documents + facts + stylized_facts + edges."""
        # stylized facts
        sf_limit_clause, sf_bind = _aql_limit("limit", limit)
        sfs = self._aql(
            f"FOR s IN stylized_facts {sf_limit_clause} RETURN s", sf_bind
        )
        sf_nodes = [_serialize_vertex(s, "stylized_fact") for s in sfs]
        sf_keys = {n["_id"] for n in sf_nodes}

        # facts that have a support edge to one of the SFs
        aql_facts = """
        LET sf_ids = (FOR s IN stylized_facts RETURN s._id)
        FOR e IN sf_support
            FILTER e._to IN sf_ids
            RETURN DISTINCT PARSE_IDENTIFIER(e._from).key
        """
        fact_keys_raw = self._aql(aql_facts, {})
        fact_keys_list = [k for k in fact_keys_raw if k]
        facts = []
        if fact_keys_list:
            facts = self._aql(
                "FOR f IN facts FILTER f._key IN @keys RETURN f",
                {"keys": fact_keys_list},
            )
        fact_nodes = [_serialize_vertex(f, "fact") for f in facts]
        fact_keys = {n["_id"] for n in fact_nodes}

        # documents that are referenced by those facts
        doc_ids = list({f.get("document_id", "") for f in facts if f.get("document_id")})
        doc_nodes = []
        if doc_ids:
            docs = self._aql(
                "FOR d IN documents FILTER d._key IN @keys RETURN d",
                {"keys": doc_ids},
            )
            doc_nodes = [_serialize_vertex(d, "document") for d in docs]
        doc_keys = {n["_id"] for n in doc_nodes}

        nodes = sf_nodes + fact_nodes + doc_nodes
        all_keys = sf_keys | fact_keys | doc_keys

        # sf_support edges (fact → stylized_fact)
        raw_sf_edges = self._aql(
            """
            FOR e IN sf_support
                RETURN {_from: e._from, _to: e._to, _key: e._key,
                        relation_type: e.relation_type || 'supports',
                        weight: e.weight || 1.0}
            """,
            {},
        )
        edges = []
        for e in raw_sf_edges:
            etype = "supports" if e.get("relation_type", "supports") == "supports" else "opposes"
            se = _serialize_edge(e["_from"], e["_to"], etype,
                                 float(e.get("weight", 1.0)), e.get("_key", ""))
            if se["source_node_id"] in all_keys and se["target_node_id"] in all_keys:
                edges.append(se)

        # extracted_from edges: fact → document (synthesized from fact.document_id)
        for fn in fact_nodes:
            doc_id = fn["properties"].get("document_id", "")
            if doc_id and doc_id in doc_keys:
                edges.append({
                    "_id": f"extracted_{fn['_id']}_{doc_id}",
                    "source_node_id": fn["_id"],
                    "target_node_id": doc_id,
                    "edge_type": "extracted_from",
                    "weight": 1.0,
                })

        _compute_degrees(nodes, edges)
        return {"nodes": nodes, "edges": edges}

    def _fetch_taxonomical(self, limit: Optional[int]) -> Dict[str, Any]:
        """Fetch taxonomy tree: taxon nodes + is_child_of edges."""
        taxa_limit_clause, taxa_bind = _aql_limit("limit", limit)
        edge_limit_clause, edge_bind = _aql_limit("edge_limit", None if limit is None else limit * 2)
        taxa = self._aql(
            f"FOR t IN taxa {taxa_limit_clause} RETURN t", taxa_bind
        )
        nodes = [_serialize_vertex(t, "taxon") for t in taxa]
        node_keys = {n["_id"] for n in nodes}

        raw_edges = self._aql(
            f"""
            FOR e IN taxonomical
                {edge_limit_clause}
                RETURN {{_from: e._from, _to: e._to, _key: e._key}}
            """,
            edge_bind,
        )
        edges = []
        for e in raw_edges:
            se = _serialize_edge(e["_from"], e["_to"], "is_child_of", 1.0, e.get("_key", ""))
            if se["source_node_id"] in node_keys and se["target_node_id"] in node_keys:
                edges.append(se)

        _compute_degrees(nodes, edges)
        return {"nodes": nodes, "edges": edges}

    def _fetch_knowledge_graph(self, limit: Optional[int]) -> Dict[str, Any]:
        """Fetch integrated knowledge graph from ArangoDB."""
        node_limit = None if limit is None else max(1, limit // 4)
        node_limit_clause, node_bind = _aql_limit("lim", node_limit)
        edge_limit_clause, edge_bind = _aql_limit("lim", limit)

        docs = self._aql(
            f"FOR d IN documents {node_limit_clause} RETURN d", node_bind
        )
        facts = self._aql(
            f"FOR f IN facts {node_limit_clause} RETURN f", node_bind
        )
        sfs = self._aql(
            f"FOR s IN stylized_facts {node_limit_clause} RETURN s", node_bind
        )
        taxa = self._aql(
            f"FOR t IN taxa {node_limit_clause} RETURN t", node_bind
        )

        nodes = (
            [_serialize_vertex(d, "document") for d in docs]
            + [_serialize_vertex(f, "fact") for f in facts]
            + [_serialize_vertex(s, "stylized_fact") for s in sfs]
            + [_serialize_vertex(t, "taxon") for t in taxa]
        )
        all_keys = {n["_id"] for n in nodes}

        raw_citations = self._aql(
            f"FOR e IN citations {edge_limit_clause} RETURN {{_from:e._from,_to:e._to,_key:e._key,w:e.weight||1.0}}",
            edge_bind,
        )
        raw_sf_support = self._aql(
            f"""FOR e IN sf_support {edge_limit_clause}
               RETURN {{_from:e._from,_to:e._to,_key:e._key,
                       rel:e.relation_type||'supports',w:e.weight||1.0}}""",
            edge_bind,
        )
        raw_kg = self._aql(
            f"FOR e IN knowledge_graph {edge_limit_clause} RETURN {{_from:e._from,_to:e._to,_key:e._key,w:e.confidence||1.0}}",
            edge_bind,
        )

        edges = []
        for e in raw_citations:
            se = _serialize_edge(e["_from"], e["_to"], "cites", float(e.get("w", 1.0)), e.get("_key", ""))
            if se["source_node_id"] in all_keys and se["target_node_id"] in all_keys:
                edges.append(se)
        for e in raw_sf_support:
            etype = "supports" if e.get("rel", "supports") == "supports" else "opposes"
            se = _serialize_edge(e["_from"], e["_to"], etype, float(e.get("w", 1.0)), e.get("_key", ""))
            if se["source_node_id"] in all_keys and se["target_node_id"] in all_keys:
                edges.append(se)
        for e in raw_kg:
            se = _serialize_edge(e["_from"], e["_to"], "studies", float(e.get("w", 1.0)), e.get("_key", ""))
            if se["source_node_id"] in all_keys and se["target_node_id"] in all_keys:
                edges.append(se)

        # synthesize extracted_from edges from fact.document_id
        doc_keys = {n["_id"] for n in nodes if n["node_type"] == "document"}
        for n in nodes:
            if n["node_type"] == "fact":
                doc_id = n["properties"].get("document_id", "")
                if doc_id and doc_id in doc_keys:
                    edges.append({
                        "_id": f"extracted_{n['_id']}_{doc_id}",
                        "source_node_id": n["_id"],
                        "target_node_id": doc_id,
                        "edge_type": "extracted_from",
                        "weight": 1.0,
                    })

        _compute_degrees(nodes, edges)
        return {"nodes": nodes, "edges": edges}

    def _fetch_physiological(self, limit: Optional[int]) -> Dict[str, Any]:
        """Fetch physiological_process graph: SFs + taxa + exhibited_by edges."""
        sf_limit_clause, sf_bind = _aql_limit("lim", limit)
        sfs = self._aql(
            f"FOR s IN stylized_facts {sf_limit_clause} RETURN s", sf_bind
        )
        sf_nodes = [_serialize_vertex(s, "stylized_fact") for s in sfs]
        sf_keys = {n["_id"] for n in sf_nodes}

        # taxa linked to SFs via sf_support → facts → knowledge_graph edges
        taxa_limit_clause, taxa_bind = _aql_limit("lim", limit)
        aql_taxa = f"""
        LET sf_ids = (FOR s IN stylized_facts RETURN s._id)
        LET fact_keys = (
            FOR e IN sf_support
                FILTER e._to IN sf_ids
                RETURN DISTINCT PARSE_IDENTIFIER(e._from).key
        )
        LET doc_ids = (
            FOR f IN facts
                FILTER f._key IN fact_keys AND f.document_id != null
                RETURN DISTINCT CONCAT('documents/', f.document_id)
        )
        LET taxon_ids = (
            FOR e IN knowledge_graph
                FILTER e._from IN doc_ids
                RETURN DISTINCT e._to
        )
        FOR t IN taxa
            FILTER CONCAT('taxa/', t._key) IN taxon_ids
            {taxa_limit_clause}
            RETURN t
        """
        taxa = self._aql(aql_taxa, taxa_bind)
        taxon_nodes = [_serialize_vertex(t, "taxon") for t in taxa]
        taxon_keys = {n["_id"] for n in taxon_nodes}

        nodes = sf_nodes + taxon_nodes
        all_keys = sf_keys | taxon_keys

        # Build exhibited_by edges: SF → taxon via confidence chain
        # sf_support: fact→SF, facts.document_id→doc, knowledge_graph: doc→taxon
        aql_edges = """
        FOR sf_edge IN sf_support
            LET sf_key = PARSE_IDENTIFIER(sf_edge._to).key
            LET fact_key = PARSE_IDENTIFIER(sf_edge._from).key
            LET fact = DOCUMENT(CONCAT('facts/', fact_key))
            FILTER fact != null AND fact.document_id != null
            LET doc_id = CONCAT('documents/', fact.document_id)
            FOR kg_edge IN knowledge_graph
                FILTER kg_edge._from == doc_id
                LET taxon_key = PARSE_IDENTIFIER(kg_edge._to).key
                RETURN DISTINCT {
                    sf_key: sf_key,
                    taxon_key: taxon_key,
                    weight: (sf_edge.confidence || 0.5) * (kg_edge.confidence || 0.5)
                }
        """
        raw = self._aql(aql_edges, {})
        edges = []
        seen: set = set()
        for row in raw:
            sk = row.get("sf_key", "")
            tk = row.get("taxon_key", "")
            if not sk or not tk:
                continue
            if sk not in all_keys or tk not in all_keys:
                continue
            pair = (sk, tk)
            if pair in seen:
                continue
            seen.add(pair)
            edges.append({
                "_id": f"exhibited_{sk}_{tk}",
                "source_node_id": sk,
                "target_node_id": tk,
                "edge_type": "exhibited_by",
                "weight": round(float(row.get("weight", 0.25)), 4),
            })

        _compute_degrees(nodes, edges)
        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Chatbot graph (requires app MongoDB for chat data)
    # ------------------------------------------------------------------

    async def _fetch_chatbot_graph(self, limit: Optional[int]) -> Dict[str, Any]:
        """Build chatbot graph from chat sessions plus linked KB context."""
        if self.app_db is None:
            logger.warning("_fetch_chatbot_graph: no app_mongo_db configured")
            return {"nodes": [], "edges": []}

        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        user_positions: Dict[str, str] = {}    # user_id str → node _id
        session_positions: Dict[str, str] = {} # session_id → node _id

        # 1. Users from chat_sessions
        user_ids_seen: set = set()
        session_cursor = self.app_db.chat_sessions.find({}) if limit is None else self.app_db.chat_sessions.find({}, limit=limit)
        async for sess in session_cursor:
            uid = str(sess.get("user_id", ""))
            sess_id = str(sess.get("_id", ""))
            # User node (deduplicated)
            if uid and uid not in user_ids_seen:
                user_ids_seen.add(uid)
                user_key = f"user_{uid}"
                user_positions[uid] = user_key
                nodes.append({
                    "_id": user_key,
                    "label": uid,
                    "node_type": "user",
                    "entity_collection": "users",
                    "entity_id": uid,
                    "cluster_id": "user",
                    "degree": 0,
                    "properties": {"user_id": uid},
                    "x": None, "y": None, "z": None, "x2d": None, "y2d": None,
                })
            # Session node
            sess_key = f"session_{sess_id}"
            session_positions[sess_id] = sess_key
            nodes.append({
                "_id": sess_key,
                "label": sess.get("title") or f"Session {sess_id[:8]}",
                "node_type": "chat_session",
                "entity_collection": "chat_sessions",
                "entity_id": sess_id,
                "cluster_id": "chat_session",
                "degree": 0,
                "properties": {
                        "user_id": uid,
                        "created_at": str(sess.get("created_at", "")),
                    },
                    "x": None, "y": None, "z": None, "x2d": None, "y2d": None,
                })
            # has_session edge: user → session
            if uid and uid in user_positions:
                edges.append({
                    "_id": f"hs_{uid}_{sess_id}",
                    "source_node_id": user_positions[uid],
                    "target_node_id": sess_key,
                    "edge_type": "has_session",
                    "weight": 1.0,
                })

        # 2. Cited document IDs from messages
        session_to_doc_ids: Dict[str, set] = {}
        async for msg in self.app_db.chat_messages.find(
            {"sources": {"$exists": True}},
            {"session_id": 1, "sources": 1},
        ):
            sess_id = str(msg.get("session_id", ""))
            sources = msg.get("sources") or []
            for src in sources:
                doc_id = src.get("document_id") or src.get("id")
                if doc_id:
                    session_to_doc_ids.setdefault(sess_id, set()).add(str(doc_id))

        # 3. Fetch cited documents from ArangoDB
        all_doc_ids = list({did for dids in session_to_doc_ids.values() for did in dids})
        doc_nodes: Dict[str, Dict] = {}
        if all_doc_ids:
            loop = asyncio.get_running_loop()
            doc_docs = await loop.run_in_executor(
                _executor,
                self._aql,
                "FOR d IN documents FILTER d._key IN @keys RETURN d",
                {"keys": all_doc_ids},
            )
            for d in doc_docs:
                node = _serialize_vertex(d, "document")
                doc_nodes[node["_id"]] = node
                nodes.append(node)

        # 4. Session → document references
        for sess_id, doc_ids in session_to_doc_ids.items():
            sess_key = session_positions.get(sess_id)
            if not sess_key:
                continue
            for doc_id in doc_ids:
                if doc_id in doc_nodes:
                    edges.append({
                        "_id": f"ref_{sess_id}_{doc_id}",
                        "source_node_id": sess_key,
                        "target_node_id": doc_id,
                        "edge_type": "references_document",
                        "weight": 1.0,
                        "properties": {},
                    })

        if not doc_nodes:
            _compute_degrees(nodes, edges)
            return {"nodes": nodes, "edges": edges}

        # 5. Facts extracted from those documents
        loop = asyncio.get_running_loop()
        fact_docs = await loop.run_in_executor(
            _executor,
            self._aql,
            "FOR f IN facts FILTER f.document_id IN @doc_ids RETURN f",
            {"doc_ids": all_doc_ids},
        )
        fact_nodes: Dict[str, Dict[str, Any]] = {}
        for fact_doc in fact_docs:
            node = _serialize_vertex(fact_doc, "fact")
            fact_nodes[node["_id"]] = node
            nodes.append(node)

        for fact_id, node in fact_nodes.items():
            doc_id = str(node.get("properties", {}).get("document_id", ""))
            if doc_id and doc_id in doc_nodes:
                edges.append({
                    "_id": f"extracted_{fact_id}_{doc_id}",
                    "source_node_id": fact_id,
                    "target_node_id": doc_id,
                    "edge_type": "extracted_from",
                    "weight": 1.0,
                    "properties": {},
                })

        # 6. Fact → stylized_fact support edges and nodes
        sf_nodes: Dict[str, Dict[str, Any]] = {}
        sf_edges_raw: List[Dict[str, Any]] = []
        fact_keys = list(fact_nodes.keys())
        if fact_keys:
            sf_edges_raw = await loop.run_in_executor(
                _executor,
                self._aql,
                """
                FOR e IN sf_support
                    FILTER PARSE_IDENTIFIER(e._from).key IN @fact_keys
                    RETURN {
                        _from: e._from,
                        _to: e._to,
                        _key: e._key,
                        relation_type: e.relation_type || 'supports',
                        weight: e.weight || 1.0
                    }
                """,
                {"fact_keys": fact_keys},
            )
            sf_keys = sorted({e["_to"].split("/")[-1] for e in sf_edges_raw if e.get("_to")})
            if sf_keys:
                sf_docs = await loop.run_in_executor(
                    _executor,
                    self._aql,
                    "FOR s IN stylized_facts FILTER s._key IN @sf_keys RETURN s",
                    {"sf_keys": sf_keys},
                )
                for sf_doc in sf_docs:
                    node = _serialize_vertex(sf_doc, "stylized_fact")
                    sf_nodes[node["_id"]] = node
                    nodes.append(node)

        for edge_doc in sf_edges_raw:
            relation_type = edge_doc.get("relation_type", "supports")
            edge_type = "supports" if relation_type == "supports" else "opposes"
            edge = _serialize_edge(
                edge_doc["_from"],
                edge_doc["_to"],
                edge_type,
                float(edge_doc.get("weight") or 1.0),
                edge_doc.get("_key", ""),
            )
            edge["properties"] = {"relation_type": relation_type}
            edges.append(edge)

        # 7. Document → taxon studies edges and taxon nodes
        taxon_nodes: Dict[str, Dict[str, Any]] = {}
        studies_edges_raw = await loop.run_in_executor(
            _executor,
            self._aql,
            """
            FOR e IN knowledge_graph
                FILTER e._from IN @doc_vertex_ids
                FILTER STARTS_WITH(e._to, 'taxa/')
                RETURN {
                    _from: e._from,
                    _to: e._to,
                    _key: e._key,
                    weight: e.confidence || 1.0
                }
            """,
            {"doc_vertex_ids": [f"documents/{doc_id}" for doc_id in all_doc_ids]},
        )
        taxon_keys = sorted({e["_to"].split("/")[-1] for e in studies_edges_raw if e.get("_to")})
        if taxon_keys:
            taxon_docs = await loop.run_in_executor(
                _executor,
                self._aql,
                "FOR t IN taxa FILTER t._key IN @taxon_keys RETURN t",
                {"taxon_keys": taxon_keys},
            )
            for taxon_doc in taxon_docs:
                node = _serialize_vertex(taxon_doc, "taxon")
                taxon_nodes[node["_id"]] = node
                nodes.append(node)

        for edge_doc in studies_edges_raw:
            edge = _serialize_edge(
                edge_doc["_from"],
                edge_doc["_to"],
                "studies",
                float(edge_doc.get("weight") or 1.0),
                edge_doc.get("_key", ""),
            )
            edges.append(edge)

        # 8. Derived stylized_fact → taxon exhibited_by edges via fact/document/taxon links
        sf_taxon_weights: Dict[tuple[str, str], float] = {}
        fact_to_sfs: Dict[str, set[str]] = {}
        for edge_doc in sf_edges_raw:
            fact_key = edge_doc.get("_from", "").split("/")[-1]
            sf_key = edge_doc.get("_to", "").split("/")[-1]
            if fact_key and sf_key:
                fact_to_sfs.setdefault(fact_key, set()).add(sf_key)

        doc_to_taxa: Dict[str, set[str]] = {}
        for edge_doc in studies_edges_raw:
            doc_key = edge_doc.get("_from", "").split("/")[-1]
            taxon_key = edge_doc.get("_to", "").split("/")[-1]
            if doc_key and taxon_key:
                doc_to_taxa.setdefault(doc_key, set()).add(taxon_key)

        for fact_key, fact_node in fact_nodes.items():
            doc_id = str(fact_node.get("properties", {}).get("document_id", ""))
            if not doc_id:
                continue
            for sf_key in fact_to_sfs.get(fact_key, set()):
                for taxon_key in doc_to_taxa.get(doc_id, set()):
                    pair = (sf_key, taxon_key)
                    sf_taxon_weights[pair] = sf_taxon_weights.get(pair, 0.0) + 1.0

        for (sf_key, taxon_key), weight in sf_taxon_weights.items():
            if sf_key in sf_nodes and taxon_key in taxon_nodes:
                edges.append({
                    "_id": f"exhibited_{sf_key}_{taxon_key}",
                    "source_node_id": sf_key,
                    "target_node_id": taxon_key,
                    "edge_type": "exhibited_by",
                    "weight": weight,
                    "properties": {"derived_from": "chatbot_context"},
                })

        _compute_degrees(nodes, edges)
        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # AQL helper
    # ------------------------------------------------------------------

    def _aql(self, query: str, bind_vars: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute AQL and return list of result documents. Logs exceptions."""
        try:
            return self.db.aql(query, bind_vars=bind_vars)
        except Exception as exc:
            logger.warning("GraphQueryService AQL failed: %s | query=%s", exc, query[:120])
            return []


# ---------------------------------------------------------------------------
# Layout functions (pure Python / NetworkX — no DB)
# ---------------------------------------------------------------------------

_LAYOUTS = {
    "force":    lambda G: nx.spring_layout(G, k=1, iterations=50, seed=42),
    "spring":   lambda G: nx.spring_layout(G, k=1, iterations=50, seed=42),
    "circular": lambda G: nx.circular_layout(G),
    "random":   lambda G: nx.random_layout(G, seed=42),
    "shell":    lambda G: nx.shell_layout(G),
}

SCHEMA_LAYOUT_MAP: Dict[str, Any] = {}   # populated at bottom of module


def _apply_layout(
    nodes: List[Dict],
    edges: List[Dict],
    schema_name: str,
) -> None:
    """Blocking layout dispatch (called in thread executor).

    Routes to the schema-specific layout function; falls back to generic
    spring layout for unrecognised schema names.
    """
    fn = SCHEMA_LAYOUT_MAP.get(schema_name, _layout_generic)
    fn(nodes, edges)


def _layout_generic(nodes: List[Dict], edges: List[Dict]) -> None:
    """Generic 2D + 3D confidence-weighted spring layout."""
    if not nodes:
        return
    G = nx.Graph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src != tgt and src in id_set and tgt in id_set:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    nc = len(G.nodes)
    if nc == 0:
        return
    k = max(0.3, 2.0 / (nc ** 0.5))
    iterations = max(15, min(50, 2000 // nc))
    scale = 250.0

    try:
        pos2d = nx.spring_layout(G, dim=2, weight="weight", k=k, iterations=iterations, seed=42)
    except Exception:
        pos2d = nx.random_layout(G, dim=2, seed=42)
    try:
        pos3d = nx.spring_layout(G, dim=3, weight="weight", k=k, iterations=iterations, seed=42)
    except Exception:
        pos3d = nx.random_layout(G, dim=3, seed=42)

    for node in nodes:
        nid = node["_id"]
        xy = pos2d.get(nid)
        xyz = pos3d.get(nid)
        node["x2d"] = round(float(xy[0]) * scale, 1) if xy is not None else 0.0
        node["y2d"] = round(float(xy[1]) * scale, 1) if xy is not None else 0.0
        node["x"]   = round(float(xyz[0]) * scale, 1) if xyz is not None else 0.0
        node["y"]   = round(float(xyz[1]) * scale, 1) if xyz is not None else 0.0
        node["z"]   = round(float(xyz[2]) * scale, 1) if xyz is not None else 0.0


def _layout_sf_support(nodes: List[Dict], edges: List[Dict]) -> None:
    """3-tier horizontal layout: documents (bottom) → facts (middle) → SFs (top)."""
    TIER = {"document": 0, "fact": 1, "stylized_fact": 2}
    TIER_Y_2D = {0: 200.0, 1: 0.0, 2: -200.0}
    TIER_Y_3D = {0: -300.0, 1: 0.0, 2: 300.0}

    G = nx.Graph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        tier = TIER.get(n.get("node_type", ""), 1)
        G.add_node(n["_id"], layer=tier)
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    pos2d = nx.multipartite_layout(G, subset_key="layer", align="horizontal", scale=200)

    _SPRING_CAP = 2000
    tier_subgraphs = {}
    for tier in [0, 1, 2]:
        tier_nodes = [nid for nid, d in G.nodes(data=True) if d.get("layer") == tier]
        if len(tier_nodes) > 1:
            if len(tier_nodes) > _SPRING_CAP:
                sorted_ids = sorted(tier_nodes, key=lambda n: hash(n) & 0xFFFFFF)
                spread = 400.0
                sub_pos = {
                    nid: ((i / (len(sorted_ids) - 1) * 2 - 1) * spread, 0.0)
                    for i, nid in enumerate(sorted_ids)
                }
            else:
                sub = G.subgraph(tier_nodes)
                k_sub = max(0.5, 3.0 / (len(tier_nodes) ** 0.5))
                try:
                    sub_pos = nx.spring_layout(sub, k=k_sub, iterations=30, seed=42)
                except Exception:
                    sub_pos = {n: (0.0, 0.0) for n in tier_nodes}
            tier_subgraphs[tier] = sub_pos
        else:
            tier_subgraphs[tier] = {nid: (0.0, 0.0) for nid in tier_nodes}

    for n in nodes:
        nid = n["_id"]
        tier = TIER.get(n.get("node_type", ""), 1)
        x2d, _ = pos2d.get(nid, (0.0, 0.0))
        n["x2d"] = round(float(x2d), 1)
        n["y2d"] = round(TIER_Y_2D[tier], 1)
        sub_pos = tier_subgraphs.get(tier, {})
        zx, _ = sub_pos.get(nid, (0.0, 0.0))
        n["x"] = round(float(x2d), 1)
        n["y"] = round(TIER_Y_3D[tier], 1)
        n["z"] = round(float(zx) * 150, 1)


def _layout_taxonomical(nodes: List[Dict], edges: List[Dict]) -> None:
    """Root taxon at top, children spread radially below."""
    G = nx.DiGraph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        G.add_node(n["_id"])
    child_to_parent = {}
    for e in edges:
        if e.get("edge_type") == "is_child_of":
            src = e.get("source_node_id")
            tgt = e.get("target_node_id")
            if src and tgt and src in id_set and tgt in id_set:
                child_to_parent[src] = tgt
                G.add_edge(src, tgt)

    children_set = set(child_to_parent.keys())
    parents_set = set(child_to_parent.values())
    candidates = parents_set - children_set
    root = next(iter(candidates)) if candidates else next(iter(id_set), None)
    if root is None:
        _layout_generic(nodes, edges)
        return

    # Build parent→children map up-front so BFS is O(n) not O(n²)
    children_map: Dict[str, List[str]] = {}
    for child, parent in child_to_parent.items():
        children_map.setdefault(parent, []).append(child)

    levels = {}
    q = deque([(root, 0)])
    visited = {root}
    while q:
        nid, depth = q.popleft()
        levels[nid] = depth
        for child in children_map.get(nid, []):
            if child not in visited:
                visited.add(child)
                q.append((child, depth + 1))

    for nid in id_set:
        if nid not in levels:
            levels[nid] = 0

    LEVEL_HEIGHT = 100
    _leaf_cache: Dict[str, int] = {}

    def count_leaves(nid):
        if nid in _leaf_cache:
            return _leaf_cache[nid]
        children = children_map.get(nid, [])
        result = sum(count_leaves(c) for c in children) if children else 1
        _leaf_cache[nid] = result
        return result

    pos_x: Dict[str, float] = {}

    def assign_x(nid, left_offset):
        w = count_leaves(nid) * 60
        pos_x[nid] = left_offset + w / 2
        cursor = left_offset
        for child in children_map.get(nid, []):
            child_w = count_leaves(child) * 60
            assign_x(child, cursor)
            cursor += child_w

    assign_x(root, 0.0)
    all_x = list(pos_x.values())
    cx = (min(all_x) + max(all_x)) / 2 if all_x else 0

    for n in nodes:
        nid = n["_id"]
        depth = levels.get(nid, 0)
        rx = pos_x.get(nid, 0.0) - cx
        ry = -depth * LEVEL_HEIGHT
        n["x2d"] = round(rx, 1)
        n["y2d"] = round(ry, 1)
        n["x"]   = round(rx, 1)
        n["y"]   = round(ry, 1)
        n["z"]   = round(float(depth) * 50 * ((hash(nid) % 100) / 100 - 0.5), 1)


def _layout_citation(nodes: List[Dict], edges: List[Dict]) -> None:
    """Community-clustered layout for citation graph."""
    G = nx.Graph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set and src != tgt:
            G.add_edge(src, tgt)

    if not G.nodes:
        return

    try:
        communities = list(nx.community.greedy_modularity_communities(G))
    except Exception:
        communities = [set(G.nodes)]

    node_community: Dict[str, int] = {}
    for i, comm in enumerate(communities):
        for nid in comm:
            node_community[nid] = i

    n_communities = len(communities)
    COMMUNITY_RADIUS = max(250, n_communities * 80)
    INTRA_RADIUS = 80

    centroids: Dict[int, tuple] = {}
    for i in range(n_communities):
        angle = 2 * math.pi * i / n_communities
        centroids[i] = (math.cos(angle) * COMMUNITY_RADIUS, math.sin(angle) * COMMUNITY_RADIUS)

    intra_pos: Dict[str, tuple] = {}
    for i, comm in enumerate(communities):
        if len(comm) < 2:
            for nid in comm:
                intra_pos[nid] = (0.0, 0.0)
            continue
        sub = G.subgraph(comm)
        k_sub = max(0.4, 2.0 / (len(comm) ** 0.5))
        iters = max(20, min(60, 1500 // len(comm)))
        try:
            sub_pos = nx.spring_layout(sub, k=k_sub, iterations=iters, seed=42, scale=INTRA_RADIUS)
        except Exception:
            sub_pos = {nid: (0.0, 0.0) for nid in comm}
        intra_pos.update(sub_pos)

    for n in nodes:
        nid = n["_id"]
        comm_idx = node_community.get(nid, 0)
        cx, cy = centroids.get(comm_idx, (0.0, 0.0))
        lx, ly = intra_pos.get(nid, (0.0, 0.0))
        n["x2d"] = round(cx + lx, 1)
        n["y2d"] = round(cy + ly, 1)
        n["x"]   = round(cx + lx, 1)
        n["y"]   = round(cy + ly, 1)
        n["z"]   = round(float(comm_idx) * 80, 1)


def _layout_knowledge_graph(nodes: List[Dict], edges: List[Dict]) -> None:
    """Hub-centered cluster layout.

    High-degree nodes end up near the centre; sparse peripheral nodes orbit
    outward.  Algorithm:
    1. Compute per-node degree.
    2. Group nodes by cluster_id.
    3. Score each cluster by its total internal degree (= its connectivity mass).
    4. Place the heaviest cluster at the origin; spread lighter clusters in
       rings of increasing radius outward so high-degree nodes stay central.
    5. Within each cluster, run a spring sub-layout seeded at (0,0) and scaled
       by cluster mass so dense clusters occupy more screen area.
    """
    if not nodes:
        return

    id_set = {n["_id"] for n in nodes}
    G = nx.Graph()
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set and src != tgt:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    # Build degree map
    degree_map: Dict[str, int] = dict(G.degree())  # type: ignore[arg-type]

    # Group by cluster
    clusters: Dict[str, List[str]] = {}
    for n in nodes:
        cid = (
            n.get("cluster_id")
            or n.get("properties", {}).get("cluster_id")
            or "default"
        )
        clusters.setdefault(cid, []).append(n["_id"])

    node_cluster: Dict[str, str] = {
        nid: cid for cid, nids in clusters.items() for nid in nids
    }

    # Score clusters by total degree mass
    cluster_mass: Dict[str, int] = {
        cid: sum(degree_map.get(nid, 0) for nid in nids)
        for cid, nids in clusters.items()
    }

    # Sort from heaviest (centre) to lightest (outer rings)
    sorted_cids = sorted(clusters.keys(), key=lambda cid: -cluster_mass[cid])
    n_clusters = len(sorted_cids)
    max_mass = max(cluster_mass.values(), default=1) or 1

    # Assign radial positions: cluster 0 at origin, rest spread outward
    BASE_RING_RADIUS = max(600, n_clusters * 120)
    INTRA_RADIUS_BASE = 80

    cluster_centroids: Dict[str, tuple] = {}
    ring_idx = 0
    for rank, cid in enumerate(sorted_cids):
        if rank == 0:
            cluster_centroids[cid] = (0.0, 0.0)
        else:
            # Pack clusters into concentric rings of ~6 per ring
            ring = (rank - 1) // 6 + 1
            pos_in_ring = (rank - 1) % 6
            ring_cap = min(6, n_clusters - 1)
            ring_radius = BASE_RING_RADIUS * ring
            theta = 2 * math.pi * pos_in_ring / max(ring_cap, 1)
            cluster_centroids[cid] = (ring_radius * math.cos(theta), ring_radius * math.sin(theta))

    # Intra-cluster spring layout; scale by cluster mass
    intra_pos: Dict[str, tuple] = {}
    _SPRING_CAP = 2000
    for cid, nids in clusters.items():
        mass = cluster_mass.get(cid, 1)
        scale = INTRA_RADIUS_BASE * (1 + 2.0 * (mass / max_mass))
        if len(nids) == 1:
            intra_pos[nids[0]] = (0.0, 0.0)
        elif len(nids) > _SPRING_CAP:
            # Too many nodes — place by degree: high-degree near centre
            sorted_nids = sorted(nids, key=lambda nid: -degree_map.get(nid, 0))
            for i, nid in enumerate(sorted_nids):
                angle = i * 2.399963
                r = scale * math.sqrt(i / len(sorted_nids))
                intra_pos[nid] = (r * math.cos(angle), r * math.sin(angle))
        else:
            sub = G.subgraph(nids)
            k_sub = max(0.5, 3.0 / (len(nids) ** 0.5))
            iters = max(10, min(40, 1000 // len(nids)))
            try:
                sp = nx.spring_layout(sub, k=k_sub, iterations=iters, seed=42, scale=scale)
            except Exception:
                sp = {nid: (0.0, 0.0) for nid in nids}
            intra_pos.update(sp)

    for n in nodes:
        nid = n["_id"]
        cid = node_cluster.get(nid, "default")
        cx, cy = cluster_centroids.get(cid, (0.0, 0.0))
        lx, ly = intra_pos.get(nid, (0.0, 0.0))
        n["x2d"] = round(cx + lx, 1)
        n["y2d"] = round(cy + ly, 1)
        n["x"]   = round(cx + lx, 1)
        n["y"]   = round(cy + ly, 1)
        rank = sorted_cids.index(cid) if cid in sorted_cids else 0
        n["z"] = round(float(rank % 20) * 300 - 3000, 1)


def _layout_physiological(nodes: List[Dict], edges: List[Dict]) -> None:
    """Confidence-weighted spring layout (2D + 3D)."""
    G = nx.Graph()
    id_set = {n["_id"] for n in nodes}
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set and src != tgt:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    nc = len(G.nodes)
    if nc == 0:
        return
    k = max(0.3, 2.0 / (nc ** 0.5))

    try:
        pos2d = nx.spring_layout(G, dim=2, weight="weight", k=k, iterations=60, seed=42)
    except Exception:
        pos2d = nx.random_layout(G, dim=2, seed=42)
    try:
        pos3d = nx.spring_layout(G, dim=3, weight="weight", k=k, iterations=30, seed=7)
    except Exception:
        pos3d = nx.random_layout(G, dim=3, seed=7)

    scale = 250
    for n in nodes:
        nid = n["_id"]
        x2, y2 = pos2d.get(nid, (0.0, 0.0))
        xyz = pos3d.get(nid, (0.0, 0.0, 0.0))
        n["x2d"] = round(float(x2) * scale, 1)
        n["y2d"] = round(float(y2) * scale, 1)
        n["x"]   = round(float(xyz[0]) * scale, 1)
        n["y"]   = round(float(xyz[1]) * scale, 1)
        n["z"]   = round(float(xyz[2]) * scale, 1)


def _layout_chatbot(nodes: List[Dict], edges: List[Dict]) -> None:
    """Hub-and-spoke layout for chatbot schema."""
    TIER = {"user": 0, "chat_session": 1, "document": 2,
            "fact": 3, "stylized_fact": 4, "taxon": 5}
    TIER_RADIUS_2D = {0: 0.0, 1: 200.0, 2: 450.0, 3: 700.0, 4: 900.0, 5: 1100.0}
    TIER_Z = {0: 0.0, 1: 100.0, 2: 200.0, 3: 300.0, 4: 400.0, 5: 500.0}

    id_set = {n["_id"] for n in nodes}

    session_to_user: Dict[str, str] = {}
    for e in edges:
        if e.get("edge_type") == "has_session":
            src = e.get("source_node_id")
            tgt = e.get("target_node_id")
            if src and tgt and src in id_set and tgt in id_set:
                session_to_user[tgt] = src

    user_nodes = [n for n in nodes if n.get("node_type") == "user"]
    user_pos: Dict[str, tuple] = {}
    n_users = len(user_nodes)
    USER_RING = 80.0
    for i, n in enumerate(user_nodes):
        angle = 2 * math.pi * i / max(n_users, 1)
        x = math.cos(angle) * USER_RING
        y = math.sin(angle) * USER_RING
        user_pos[n["_id"]] = (x, y)
        n["x2d"] = round(x, 1);  n["y2d"] = round(y, 1)
        n["x"]   = round(x, 1);  n["y"]   = round(y, 1)
        n["z"]   = round(TIER_Z[0], 1)

    session_nodes = [n for n in nodes if n.get("node_type") == "chat_session"]
    user_sessions: Dict[str, List[str]] = {}
    for sn in session_nodes:
        uid = session_to_user.get(sn["_id"])
        if uid:
            user_sessions.setdefault(uid, []).append(sn["_id"])

    session_pos: Dict[str, tuple] = {}
    for uid, sess_ids in user_sessions.items():
        ux, uy = user_pos.get(uid, (0.0, 0.0))
        n_sess = len(sess_ids)
        for j, sid in enumerate(sess_ids):
            angle = 2 * math.pi * j / max(n_sess, 1)
            session_pos[sid] = (ux + math.cos(angle) * TIER_RADIUS_2D[1],
                                uy + math.sin(angle) * TIER_RADIUS_2D[1])

    orphan_sessions = [sn["_id"] for sn in session_nodes if sn["_id"] not in session_pos]
    for k, sid in enumerate(orphan_sessions):
        angle = 2 * math.pi * k / max(len(orphan_sessions), 1)
        session_pos[sid] = (math.cos(angle) * TIER_RADIUS_2D[1],
                            math.sin(angle) * TIER_RADIUS_2D[1])

    for sn in session_nodes:
        x, y = session_pos.get(sn["_id"], (0.0, 0.0))
        sn["x2d"] = round(x, 1);  sn["y2d"] = round(y, 1)
        sn["x"]   = round(x, 1);  sn["y"]   = round(y, 1)
        sn["z"]   = round(TIER_Z[1], 1)

    G = nx.Graph()
    for n in nodes:
        G.add_node(n["_id"])
    for e in edges:
        src, tgt = e.get("source_node_id"), e.get("target_node_id")
        if src and tgt and src in id_set and tgt in id_set and src != tgt:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))

    for tier_name, tier_idx in [("document", 2), ("fact", 3), ("stylized_fact", 4), ("taxon", 5)]:
        tier_nodes = [n for n in nodes if n.get("node_type") == tier_name]
        if not tier_nodes:
            continue
        radius = TIER_RADIUS_2D[tier_idx]
        z_val = TIER_Z[tier_idx]
        n_tier = len(tier_nodes)
        if n_tier == 1:
            tier_nodes[0].update({"x2d": round(radius, 1), "y2d": 0.0,
                                   "x": round(radius, 1), "y": 0.0, "z": round(z_val, 1)})
            continue
        for idx, n in enumerate(sorted(tier_nodes, key=lambda x: x["_id"])):
            angle = 2 * math.pi * idx / n_tier
            n["x2d"] = round(math.cos(angle) * radius, 1)
            n["y2d"] = round(math.sin(angle) * radius, 1)
            n["x"]   = round(math.cos(angle) * radius, 1)
            n["y"]   = round(math.sin(angle) * radius, 1)
            n["z"]   = round(z_val + (hash(n["_id"]) % 100) * 0.5, 1)


# Populate dispatch map
SCHEMA_LAYOUT_MAP["sf_support"]            = _layout_sf_support
SCHEMA_LAYOUT_MAP["taxonomical"]           = _layout_taxonomical
SCHEMA_LAYOUT_MAP["citation"]              = _layout_citation
SCHEMA_LAYOUT_MAP["knowledge_graph"]       = _layout_knowledge_graph
SCHEMA_LAYOUT_MAP["physiological_process"] = _layout_physiological
SCHEMA_LAYOUT_MAP["chatbot"]               = _layout_chatbot
