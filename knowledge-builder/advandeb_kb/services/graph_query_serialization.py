"""
Serialization helpers for the graph query layer.

Extracted from the original ``graph_query_service.py`` so the schema → ArangoDB
config, the vertex/edge serializers, and the degree-computation helper can be
reused by fetcher modules and external callers (e.g. graph_artifact_builder)
without pulling in the full service class.

Public surface (re-exported from ``graph_query_service``):
    _compute_degrees, _serialize_vertex, _serialize_edge
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


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
        # Handled separately in fetch_chatbot_graph().
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
    """Build the AQL ``LIMIT @name`` clause + bind dict, or empty when limit is None."""
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
