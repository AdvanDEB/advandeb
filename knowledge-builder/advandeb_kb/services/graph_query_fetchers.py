"""
Per-schema ArangoDB fetchers for the graph query layer.

Extracted from ``graph_query_service.py``. Each ``fetch_*`` function takes the
ArangoDatabase handle (and, for the chatbot schema, the app Motor database)
and returns a ``{"nodes": [...], "edges": [...]}`` dict.

These functions are synchronous (the chatbot fetcher is async because it must
touch both ArangoDB and the app Mongo). The service class dispatches the sync
ones via ``run_in_executor`` so callers from async code never block.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from advandeb_kb.database.arango_client import ArangoDatabase
from advandeb_kb.services.graph_query_serialization import (
    _SCHEMA_ARANGO,
    _aql_limit,
    _compute_degrees,
    _serialize_edge,
    _serialize_vertex,
    FACT_NODE_TYPES,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AQL helper
# ---------------------------------------------------------------------------

def aql(db: ArangoDatabase, query: str, bind_vars: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute AQL and return list of result documents. Logs exceptions."""
    try:
        return db.aql(query, bind_vars=bind_vars)
    except Exception as exc:
        logger.warning("graph_query AQL failed: %s | query=%s", exc, query[:120])
        return []


# ---------------------------------------------------------------------------
# Synchronous dispatcher
# ---------------------------------------------------------------------------

def fetch_graph_sync(
    db: ArangoDatabase,
    schema_name: str,
    limit: Optional[int],
) -> Dict[str, Any]:
    """Blocking fetch — meant to run in a thread executor."""
    cfg = _SCHEMA_ARANGO.get(schema_name)
    if cfg is None:
        logger.warning("fetch_graph_sync: unknown schema %r", schema_name)
        return {"nodes": [], "edges": []}

    if schema_name == "citation":
        return fetch_citation(db, limit)
    if schema_name == "sf_support":
        return fetch_sf_support(db, limit)
    if schema_name == "taxonomical":
        return fetch_taxonomical(db, limit)
    if schema_name == "knowledge_graph":
        return fetch_knowledge_graph(db, limit)
    if schema_name == "physiological_process":
        return fetch_physiological(db, limit)
    if schema_name == "reproduction":
        return fetch_reproduction(db, limit)
    return {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# Per-schema sync fetchers
# ---------------------------------------------------------------------------

def fetch_citation(db: ArangoDatabase, limit: Optional[int]) -> Dict[str, Any]:
    """Fetch citation graph: document nodes + cites edges."""
    doc_limit_clause, doc_bind = _aql_limit("limit", limit)
    edge_limit_clause, edge_bind = _aql_limit("edge_limit", None if limit is None else limit * 2)
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
    docs = aql(db, aql_docs, doc_bind)
    nodes = [_serialize_vertex(d, "document") for d in docs]
    node_keys = {n["_id"] for n in nodes}

    raw_edges = aql(db, aql_edges, edge_bind)
    edges = []
    for e in raw_edges:
        se = _serialize_edge(e["_from"], e["_to"], "cites",
                             float(e.get("weight", 1.0)), e.get("_key", ""))
        if se["source_node_id"] in node_keys and se["target_node_id"] in node_keys:
            edges.append(se)

    _compute_degrees(nodes, edges)
    return {"nodes": nodes, "edges": edges}


def fetch_sf_support(db: ArangoDatabase, limit: Optional[int]) -> Dict[str, Any]:
    """Fetch sf_support graph: documents + facts + stylized_facts + edges."""
    # stylized facts
    sf_limit_clause, sf_bind = _aql_limit("limit", limit)
    sfs = aql(db,
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
    fact_keys_raw = aql(db, aql_facts, {})
    fact_keys_list = [k for k in fact_keys_raw if k]
    facts = []
    if fact_keys_list:
        facts = aql(db,
            "FOR f IN facts FILTER f._key IN @keys RETURN f",
            {"keys": fact_keys_list},
        )
    fact_nodes = [_serialize_vertex(f, "fact") for f in facts]
    fact_keys = {n["_id"] for n in fact_nodes}

    # documents that are referenced by those facts
    doc_ids = list({f.get("document_id", "") for f in facts if f.get("document_id")})
    doc_nodes = []
    if doc_ids:
        docs = aql(db,
            "FOR d IN documents FILTER d._key IN @keys RETURN d",
            {"keys": doc_ids},
        )
        doc_nodes = [_serialize_vertex(d, "document") for d in docs]
    doc_keys = {n["_id"] for n in doc_nodes}

    nodes = sf_nodes + fact_nodes + doc_nodes
    all_keys = sf_keys | fact_keys | doc_keys

    # sf_support edges (fact → stylized_fact)
    raw_sf_edges = aql(db,
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
                "properties": {},
            })

    _compute_degrees(nodes, edges)
    return {"nodes": nodes, "edges": edges}


# The `taxa` collection is a full NCBI backbone import (~1.26M rows). It exists
# so the ingestion pipeline can resolve any organism name it meets; it is not a
# graph anybody can read. The taxonomical schema therefore shows the organisms
# the corpus actually studies, plus the lineage that connects them to the root.
_TAXON_BACKBONE_RANKS = ["superkingdom", "kingdom", "phylum", "class", "order", "family"]

# Cap for the no-seeds fallback below — the backbone down to family is ~8k nodes.
_TAXON_FALLBACK_LIMIT = 10_000

_TAXON_SCOPE_AQL = """
LET seeds = (
    FOR e IN knowledge_graph
        FOR side IN [e._from, e._to]
            FILTER STARTS_WITH(side, 'taxa/')
            RETURN DISTINCT PARSE_IDENTIFIER(side).key
)
LET closure = UNIQUE(FLATTEN(
    FOR k IN seeds
        LET t = DOCUMENT('taxa', k)
        FILTER t != null
        RETURN APPEND(t.lineage[* RETURN TO_STRING(CURRENT)], [t._key])
))
RETURN {seeds: seeds, closure: closure}
"""


def fetch_taxonomical(db: ArangoDatabase, limit: Optional[int]) -> Dict[str, Any]:
    """Fetch the taxonomy tree scoped to taxa the knowledge base actually uses.

    Nodes are the taxa referenced by ``knowledge_graph`` edges (documents that
    study an organism) together with every ancestor on their ``lineage`` — the
    ancestors are what make the result a connected tree rather than a scatter of
    unrelated species. Taxa reached from the corpus carry ``properties.studied``
    so the UI can pick them out from the lineage scaffolding around them.

    When nothing references a taxon yet the graph would be empty, so it falls
    back to the high-rank backbone (down to family) as an orientation view.
    """
    scope = aql(db, _TAXON_SCOPE_AQL, {})
    seeds: List[str] = list(scope[0].get("seeds") or []) if scope else []
    closure: List[str] = list(scope[0].get("closure") or []) if scope else []

    if closure:
        taxa = aql(db, "FOR t IN DOCUMENT('taxa', @keys) RETURN t", {"keys": closure})
        scoped = True
    else:
        logger.info("taxonomical: no taxa referenced by knowledge_graph — falling back to rank backbone")
        fallback_limit = min(limit or _TAXON_FALLBACK_LIMIT, _TAXON_FALLBACK_LIMIT)
        taxa = aql(db,
            "FOR t IN taxa FILTER t.rank IN @ranks LIMIT @lim RETURN t",
            {"ranks": _TAXON_BACKBONE_RANKS, "lim": fallback_limit},
        )
        scoped = False

    seed_keys = set(seeds)
    nodes = []
    for t in taxa:
        node = _serialize_vertex(t, "taxon")
        node["properties"]["studied"] = node["_id"] in seed_keys
        nodes.append(node)
    node_keys = {n["_id"] for n in nodes}

    # Build is_child_of edges from each taxon's own parent pointer rather than
    # scanning the 1.26M-row `taxonomical` edge collection: the parent link is
    # already on the document, and this guarantees every edge stays inside the
    # scoped node set. Key format matches the stored edges (`<child>_to_<parent>`).
    edges = []
    for t in taxa:
        child = str(t.get("_key", ""))
        parent = str(t.get("parent_tax_id") or "")
        if not child or not parent or child == parent:
            continue
        if child in node_keys and parent in node_keys:
            edges.append(
                _serialize_edge(child, parent, "is_child_of", 1.0, f"{child}_to_{parent}")
            )

    _compute_degrees(nodes, edges)
    logger.info(
        "taxonomical: %d nodes / %d edges (%s, %d studied)",
        len(nodes), len(edges), "scoped to corpus" if scoped else "rank backbone", len(seed_keys),
    )
    return {"nodes": nodes, "edges": edges}


# The integrated graph joins four collections, three of which are far too big to
# show whole: documents (~3.9M), taxa (~1.26M), facts (~109k). A blind `LIMIT n`
# over each takes an arbitrary first-n slice, and an edge only survives if BOTH
# endpoints land inside their slice — so the *rarest* edge type is the one that
# vanishes. That is exactly what happened to `studies`: 35 edges in
# `knowledge_graph`, spanning 22 documents and 28 taxa that are nowhere near the
# front of a 3.9M / 1.26M scan, of which a single edge used to survive.
#
# So scope each collection to what actually carries an edge — the taxa the corpus
# studies plus the lineage that connects them, the documents that cite / are
# cited / are a fact's source, and the facts that support or oppose a stylized
# fact. Everything left out was an isolated dot in the view anyway.
_KG_SCOPE_AQL = """
LET kg_docs = (
    FOR e IN knowledge_graph
        FILTER STARTS_WITH(e._from, 'documents/')
        RETURN DISTINCT PARSE_IDENTIFIER(e._from).key
)
LET kg_facts = (
    FOR e IN knowledge_graph
        FILTER STARTS_WITH(e._from, 'facts/')
        RETURN DISTINCT PARSE_IDENTIFIER(e._from).key
)
LET kg_taxa = (
    FOR e IN knowledge_graph
        FOR side IN [e._from, e._to]
            FILTER STARTS_WITH(side, 'taxa/')
            RETURN DISTINCT PARSE_IDENTIFIER(side).key
)
LET taxa_closure = UNIQUE(FLATTEN(
    FOR k IN kg_taxa
        LET t = DOCUMENT('taxa', k)
        FILTER t != null
        RETURN APPEND(t.lineage[* RETURN TO_STRING(CURRENT)], [t._key])
))
LET cite_docs = (
    FOR e IN citations
        FOR side IN [e._from, e._to]
            FILTER STARTS_WITH(side, 'documents/')
            RETURN DISTINCT PARSE_IDENTIFIER(side).key
)
LET supported_facts = (
    FOR e IN sf_support
        FILTER STARTS_WITH(e._from, 'facts/')
        RETURN DISTINCT PARSE_IDENTIFIER(e._from).key
)
RETURN {kg_docs: kg_docs, kg_facts: kg_facts, kg_taxa: kg_taxa,
        taxa_closure: taxa_closure, cite_docs: cite_docs,
        supported_facts: supported_facts}
"""


def _load_by_keys(db: ArangoDatabase, collection: str, keys: List[str]) -> List[Dict[str, Any]]:
    """Load documents by ``_key`` in one round trip, dropping keys that miss.

    ``DOCUMENT(coll, keys)`` silently skips keys with no row, which is what we
    want here: a taxon's ``lineage`` names ancestors (1, 131567, …) that the NCBI
    backbone import does not carry as documents.
    """
    if not keys:
        return []
    return aql(db,
        "FOR d IN DOCUMENT(@coll, @keys) FILTER d != null RETURN d",
        {"coll": collection, "keys": list(keys)},
    )


def fetch_knowledge_graph(db: ArangoDatabase, limit: Optional[int]) -> Dict[str, Any]:
    """Fetch the integrated knowledge graph, scoped to entities that carry edges.

    The point of this view is the document→organism link, so the taxa are the
    ones ``knowledge_graph`` edges reference plus their ancestor ``lineage``
    closure (the scaffolding that makes them a tree rather than a scatter), and
    the documents are the ones that participate in an edge — never a blind slice
    of the multi-million-row backbone imports. See ``_KG_SCOPE_AQL`` above.
    """
    edge_limit_clause, edge_bind = _aql_limit("lim", limit)

    scope_rows = aql(db, _KG_SCOPE_AQL, {})
    scope = scope_rows[0] if scope_rows else {}
    kg_doc_keys: List[str] = list(scope.get("kg_docs") or [])
    cite_doc_keys: List[str] = list(scope.get("cite_docs") or [])
    taxa_closure: List[str] = list(scope.get("taxa_closure") or [])
    # `knowledge_graph` is declared as documents,facts → taxa,stylized_facts. Only
    # the document→taxon half is populated today, but a fact that studies a taxon
    # without also supporting a stylized fact would otherwise miss the scope, so
    # take those facts first and keep them ahead of the budget cap below.
    kg_fact_keys: List[str] = list(scope.get("kg_facts") or [])
    supported_fact_keys: List[str] = list(dict.fromkeys(
        kg_fact_keys + list(scope.get("supported_facts") or [])
    ))

    # taxa (lineage closure) and stylized facts are the small structural layers —
    # a few hundred / ~1.2k rows. Take them whole; capping them buys nothing and
    # a missing ancestor breaks the tree.
    taxa = _load_by_keys(db, "taxa", taxa_closure)
    sfs = aql(db, "FOR s IN stylized_facts RETURN s", {})

    # `facts` is the only layer that can realistically outgrow the node budget,
    # so it is the only one that keeps a cap. Documents are derived from the
    # facts that survive, so the extracted_from edges stay whole.
    spent = len(taxa) + len(sfs) + len(kg_doc_keys) + len(cite_doc_keys)
    if limit is not None and len(supported_fact_keys) > max(0, limit - spent):
        keep = max(0, limit - spent)
        logger.warning(
            "knowledge_graph: node budget %d truncates facts %d → %d; "
            "raise GRAPH_ARTIFACT_MAX_NODES for a fuller graph.",
            limit, len(supported_fact_keys), keep,
        )
        supported_fact_keys = supported_fact_keys[:keep]
    facts = _load_by_keys(db, "facts", supported_fact_keys)

    # kg docs first: they are the `studies` endpoints and must never be the ones
    # dropped if the union ever has to be trimmed.
    fact_doc_keys = sorted({f.get("document_id") for f in facts if f.get("document_id")})
    scoped_doc_keys = list(dict.fromkeys(kg_doc_keys + cite_doc_keys + fact_doc_keys))
    if limit is not None:
        scoped_doc_keys = scoped_doc_keys[: max(0, limit - len(taxa) - len(sfs) - len(facts))]
    docs = _load_by_keys(db, "documents", scoped_doc_keys)

    nodes = (
        [_serialize_vertex(d, "document") for d in docs]
        + [_serialize_vertex(f, "fact") for f in facts]
        + [_serialize_vertex(s, "stylized_fact") for s in sfs]
        + [_serialize_vertex(t, "taxon") for t in taxa]
    )
    all_keys = {n["_id"] for n in nodes}

    raw_citations = aql(db,
        f"FOR e IN citations {edge_limit_clause} RETURN {{_from:e._from,_to:e._to,_key:e._key,w:e.weight||1.0}}",
        edge_bind,
    )
    raw_sf_support = aql(db,
        f"""FOR e IN sf_support {edge_limit_clause}
           RETURN {{_from:e._from,_to:e._to,_key:e._key,
                   rel:e.relation_type||'supports',w:e.weight||1.0}}""",
        edge_bind,
    )
    raw_kg = aql(db,
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
    doc_keys = {n["_id"] for n in nodes if n["node_type"] in ("document", "abstract")}
    for n in nodes:
        if n["node_type"] in FACT_NODE_TYPES:
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
    studies = sum(1 for e in edges if e.get("edge_type") == "studies")
    logger.info(
        "knowledge_graph: %d nodes (%d doc / %d fact / %d sf / %d taxon) / %d edges "
        "(%d studies of %d in scope)",
        len(nodes), len(docs), len(facts), len(sfs), len(taxa), len(edges),
        studies, len(raw_kg),
    )
    return {"nodes": nodes, "edges": edges}


def fetch_reproduction(db: ArangoDatabase, limit: Optional[int]) -> Dict[str, Any]:
    """Reproduction-domain subgraph.

    Documents tagged ``general_domain == 'reproduction'`` plus the facts extracted
    from them, the stylized facts those facts support/oppose, and the taxa those
    documents study — and the edges among them. Mirrors ``fetch_knowledge_graph``
    but scoped to the reproduction domain rather than the whole KB.
    """
    node_limit = None if limit is None else max(1, limit // 4)
    node_limit_clause, node_bind = _aql_limit("lim", node_limit)
    edge_limit_clause, edge_bind = _aql_limit("lim", limit)

    # Documents scoped to the reproduction domain. Prefer abstracts that have
    # already been processed (so the graph surfaces their extracted conclusions /
    # background knowledge / citations); fall back to bare abstracts only if none
    # have been processed yet.
    docs = aql(db,
        f"FOR d IN documents FILTER d.general_domain == 'reproduction' "
        f"AND d.processing_status == 'completed' {node_limit_clause} RETURN d",
        node_bind,
    )
    if not docs:
        docs = aql(db,
            f"FOR d IN documents FILTER d.general_domain == 'reproduction' {node_limit_clause} RETURN d",
            node_bind,
        )
    doc_nodes = [_serialize_vertex(d, "document") for d in docs]
    doc_key_set = {n["_id"] for n in doc_nodes}
    if not doc_key_set:
        return {"nodes": [], "edges": []}
    doc_keys = list(doc_key_set)

    # Facts extracted from those documents (fact.document_id == document _key)
    facts = aql(db,
        f"FOR f IN facts FILTER f.document_id IN @doc_keys {node_limit_clause} RETURN f",
        {"doc_keys": doc_keys, **node_bind},
    )
    fact_nodes = [_serialize_vertex(f, "fact") for f in facts]
    fact_keys = [n["_id"] for n in fact_nodes]

    # Stylized facts supported/opposed by those facts
    sf_edges_raw: List[Dict[str, Any]] = []
    sf_nodes: List[Dict[str, Any]] = []
    if fact_keys:
        sf_edges_raw = aql(db,
            """
            FOR e IN sf_support
                FILTER PARSE_IDENTIFIER(e._from).key IN @fact_keys
                RETURN {_from: e._from, _to: e._to, _key: e._key,
                        rel: e.relation_type || 'supports',
                        w: e.weight || e.confidence || 1.0}
            """,
            {"fact_keys": fact_keys},
        )
        sf_key_set = sorted({e["_to"].split("/")[-1] for e in sf_edges_raw if e.get("_to")})
        if sf_key_set:
            sfs = aql(db,
                "FOR s IN stylized_facts FILTER s._key IN @sf_keys RETURN s",
                {"sf_keys": sf_key_set},
            )
            sf_nodes = [_serialize_vertex(s, "stylized_fact") for s in sfs]

    # Taxa studied by those documents (knowledge_graph edge: documents/<k> → taxa/<k>)
    studies_edges_raw = aql(db,
        """
        FOR e IN knowledge_graph
            FILTER e._from IN @doc_vertex_ids AND STARTS_WITH(e._to, 'taxa/')
            RETURN {_from: e._from, _to: e._to, _key: e._key, w: e.confidence || 1.0}
        """,
        {"doc_vertex_ids": [f"documents/{k}" for k in doc_keys]},
    )
    taxon_nodes: List[Dict[str, Any]] = []
    taxon_key_set = sorted({e["_to"].split("/")[-1] for e in studies_edges_raw if e.get("_to")})
    if taxon_key_set:
        taxa = aql(db,
            "FOR t IN taxa FILTER t._key IN @taxon_keys RETURN t",
            {"taxon_keys": taxon_key_set},
        )
        taxon_nodes = [_serialize_vertex(t, "taxon") for t in taxa]

    nodes = doc_nodes + fact_nodes + sf_nodes + taxon_nodes
    all_keys = {n["_id"] for n in nodes}

    edges: List[Dict[str, Any]] = []

    # citation edges among reproduction documents
    raw_citations = aql(db,
        f"FOR e IN citations {edge_limit_clause} "
        f"RETURN {{_from:e._from,_to:e._to,_key:e._key,w:e.weight||1.0}}",
        edge_bind,
    )
    for e in raw_citations:
        se = _serialize_edge(e["_from"], e["_to"], "cites", float(e.get("w", 1.0)), e.get("_key", ""))
        if se["source_node_id"] in doc_key_set and se["target_node_id"] in doc_key_set:
            edges.append(se)

    # supports / opposes (fact → stylized_fact)
    for e in sf_edges_raw:
        etype = "supports" if e.get("rel", "supports") == "supports" else "opposes"
        se = _serialize_edge(e["_from"], e["_to"], etype, float(e.get("w", 1.0)), e.get("_key", ""))
        if se["source_node_id"] in all_keys and se["target_node_id"] in all_keys:
            edges.append(se)

    # studies (document → taxon)
    for e in studies_edges_raw:
        se = _serialize_edge(e["_from"], e["_to"], "studies", float(e.get("w", 1.0)), e.get("_key", ""))
        if se["source_node_id"] in all_keys and se["target_node_id"] in all_keys:
            edges.append(se)

    # extracted_from (fact → document), synthesized from fact.document_id
    for fn in fact_nodes:
        doc_id = fn["properties"].get("document_id", "")
        if doc_id and doc_id in doc_key_set:
            edges.append({
                "_id": f"extracted_{fn['_id']}_{doc_id}",
                "source_node_id": fn["_id"],
                "target_node_id": doc_id,
                "edge_type": "extracted_from",
                "weight": 1.0,
                "properties": {},
            })

    _compute_degrees(nodes, edges)
    return {"nodes": nodes, "edges": edges}


def fetch_physiological(db: ArangoDatabase, limit: Optional[int]) -> Dict[str, Any]:
    """Fetch physiological_process graph: SFs + taxa + exhibited_by edges."""
    sf_limit_clause, sf_bind = _aql_limit("lim", limit)
    sfs = aql(db,
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
    taxa = aql(db, aql_taxa, taxa_bind)
    taxon_nodes = [_serialize_vertex(t, "taxon") for t in taxa]
    taxon_keys = {n["_id"] for n in taxon_nodes}

    nodes = sf_nodes + taxon_nodes
    all_keys = sf_keys | taxon_keys

    # Build exhibited_by edges: SF → taxon via confidence chain
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
    raw = aql(db, aql_edges, {})
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


# ---------------------------------------------------------------------------
# Chatbot graph fetcher (async — touches both ArangoDB and app Mongo)
# ---------------------------------------------------------------------------

async def fetch_chatbot_graph(
    db: ArangoDatabase,
    app_mongo_db: Any,
    executor: ThreadPoolExecutor,
    limit: Optional[int],
) -> Dict[str, Any]:
    """Build chatbot graph from chat sessions plus linked KB context.

    Requires an app Motor database (``app_mongo_db``) for chat_sessions and
    chat_messages.  The ArangoDB lookups for documents/facts/SFs/taxa are
    dispatched via ``executor`` so this stays non-blocking.
    """
    if app_mongo_db is None:
        logger.warning("fetch_chatbot_graph: no app_mongo_db configured")
        return {"nodes": [], "edges": []}

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    user_positions: Dict[str, str] = {}    # user_id str → node _id
    session_positions: Dict[str, str] = {}  # session_id → node _id

    # 1. Users from chat_sessions
    user_ids_seen: set = set()
    session_cursor = (
        app_mongo_db.chat_sessions.find({})
        if limit is None
        else app_mongo_db.chat_sessions.find({}, limit=limit)
    )
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
    async for msg in app_mongo_db.chat_messages.find(
        {"citations": {"$exists": True, "$ne": []}},
        {"session_id": 1, "citations": 1},
    ):
        sess_id = str(msg.get("session_id", ""))
        for cit in msg.get("citations") or []:
            doc_id = cit.get("document_id") or cit.get("id")
            if doc_id:
                session_to_doc_ids.setdefault(sess_id, set()).add(str(doc_id))

    # 3. Fetch cited documents from ArangoDB
    all_doc_ids = list({did for dids in session_to_doc_ids.values() for did in dids})
    doc_nodes: Dict[str, Dict] = {}
    if all_doc_ids:
        loop = asyncio.get_running_loop()
        doc_docs = await loop.run_in_executor(
            executor,
            aql,
            db,
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
        executor,
        aql,
        db,
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
            executor,
            aql,
            db,
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
                executor,
                aql,
                db,
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
        executor,
        aql,
        db,
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
            executor,
            aql,
            db,
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
