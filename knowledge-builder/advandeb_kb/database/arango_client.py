"""
ArangoDB client and schema setup for advandeb_kb.

Collections (document):
    documents, facts, stylized_facts, taxa, chunks, provenance_traces

Edge collections:
    citations          — Document → Document
    sf_support         — Fact → StylizedFact (support/oppose)
    taxonomical        — TaxonomyNode → TaxonomyNode (parent/child)
    knowledge_graph    — Document/Fact → TaxonomyNode
    chunk_belongs_to   — Chunk → Document

Named graphs:
    citation_graph, support_graph, taxonomy_graph, knowledge_graph, chunk_graph
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from advandeb_kb.config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

DOCUMENT_COLLECTIONS = [
    "documents",
    "facts",
    "stylized_facts",
    "taxa",
    "chunks",
    "provenance_traces",
]

EDGE_COLLECTIONS = [
    "citations",
    "sf_support",
    "taxonomical",
    "knowledge_graph",
    "chunk_belongs_to",
]

NAMED_GRAPHS = {
    "citation_graph": {
        "edge_definitions": [
            {
                "edge_collection": "citations",
                "from_vertex_collections": ["documents"],
                "to_vertex_collections": ["documents"],
            }
        ]
    },
    "support_graph": {
        "edge_definitions": [
            {
                "edge_collection": "sf_support",
                "from_vertex_collections": ["facts"],
                "to_vertex_collections": ["stylized_facts"],
            }
        ]
    },
    "taxonomy_graph": {
        "edge_definitions": [
            {
                "edge_collection": "taxonomical",
                "from_vertex_collections": ["taxa"],
                "to_vertex_collections": ["taxa"],
            }
        ]
    },
    "knowledge_graph": {
        "edge_definitions": [
            {
                "edge_collection": "knowledge_graph",
                "from_vertex_collections": ["documents", "facts"],
                "to_vertex_collections": ["taxa", "stylized_facts"],
            }
        ]
    },
    "chunk_graph": {
        "edge_definitions": [
            {
                "edge_collection": "chunk_belongs_to",
                "from_vertex_collections": ["chunks"],
                "to_vertex_collections": ["documents"],
            }
        ]
    },
}

# ArangoDB full-text index fields (enables keyword search)
FULLTEXT_INDEXES = [
    ("documents", "content"),
    ("documents", "abstract"),
    ("facts", "text"),
    ("stylized_facts", "description"),
    ("chunks", "text"),
]


# ---------------------------------------------------------------------------
# ArangoDatabase
# ---------------------------------------------------------------------------


class ArangoDatabase:
    """
    Synchronous ArangoDB client wrapping python-arango.

    Usage:
        db = ArangoDatabase()
        db.connect()
        db.setup_schema()
    """

    def __init__(
        self,
        url: Optional[str] = None,
        db_name: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.url = url or settings.ARANGO_URL
        self.db_name = db_name or settings.ARANGO_DB_NAME
        self.username = username or settings.ARANGO_USERNAME
        self.password = password or settings.ARANGO_PASSWORD

        self._client = None
        self._db = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open connection and ensure DB exists."""
        from arango import ArangoClient

        self._client = ArangoClient(hosts=self.url)
        sys_db = self._client.db("_system", username=self.username, password=self.password)

        if not sys_db.has_database(self.db_name):
            sys_db.create_database(self.db_name)
            logger.info("Created ArangoDB database: %s", self.db_name)

        self._db = self._client.db(
            self.db_name, username=self.username, password=self.password
        )
        logger.info("Connected to ArangoDB: %s/%s", self.url, self.db_name)

    def disconnect(self) -> None:
        self._client = None
        self._db = None

    @property
    def db(self):
        if self._db is None:
            raise RuntimeError("ArangoDatabase.connect() must be called first.")
        return self._db

    def ping(self) -> bool:
        try:
            self.db.properties()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Schema setup
    # ------------------------------------------------------------------

    def setup_schema(self, drop_existing: bool = False) -> None:
        """Create all collections, edge collections, indexes, and named graphs."""
        if drop_existing:
            self._drop_all()

        self._create_collections()
        self._create_edge_collections()
        self._create_indexes()
        self._create_graphs()
        logger.info("ArangoDB schema setup complete.")

    def _create_collections(self) -> None:
        for name in DOCUMENT_COLLECTIONS:
            if not self.db.has_collection(name):
                self.db.create_collection(name)
                logger.debug("Created collection: %s", name)

    def _create_edge_collections(self) -> None:
        for name in EDGE_COLLECTIONS:
            if not self.db.has_collection(name):
                self.db.create_collection(name, edge=True)
                logger.debug("Created edge collection: %s", name)

    def _create_indexes(self) -> None:
        for collection_name, field in FULLTEXT_INDEXES:
            col = self.db.collection(collection_name)
            existing = [idx["fields"] for idx in col.indexes()]
            if [field] not in existing:
                col.add_fulltext_index(fields=[field], min_length=3)
                logger.debug("Created fulltext index on %s.%s", collection_name, field)

        # Persistent (btree) indexes for common lookups
        persistent_indexes = [
            ("documents", ["doi"], True, True),     # unique DOI, sparse (nulls excluded)
            ("documents", ["year"], False, False),
            ("facts", ["document_id"], False, False),
            ("facts", ["status"], False, False),
            ("stylized_facts", ["sf_number"], True, True),
            ("taxa", ["tax_id"], True, True),
            ("taxa", ["rank"], False, False),
            ("chunks", ["document_id"], False, False),
            ("chunks", ["chunk_index"], False, False),
        ]
        for collection_name, fields, unique, sparse in persistent_indexes:
            col = self.db.collection(collection_name)
            existing_fields = [idx["fields"] for idx in col.indexes()]
            if fields not in existing_fields:
                col.add_persistent_index(fields=fields, unique=unique, sparse=sparse)
                logger.debug(
                    "Created persistent index on %s%s: %s",
                    collection_name,
                    " (unique)" if unique else "",
                    fields,
                )

    def _create_graphs(self) -> None:
        for graph_name, graph_def in NAMED_GRAPHS.items():
            if not self.db.has_graph(graph_name):
                self.db.create_graph(
                    graph_name,
                    edge_definitions=graph_def["edge_definitions"],
                )
                logger.debug("Created graph: %s", graph_name)

    def _drop_all(self) -> None:
        for name in NAMED_GRAPHS:
            if self.db.has_graph(name):
                self.db.delete_graph(name, drop_collections=False)
        for name in EDGE_COLLECTIONS + DOCUMENT_COLLECTIONS:
            if self.db.has_collection(name):
                self.db.delete_collection(name)
        logger.warning("Dropped all advandeb_kb collections and graphs.")

    # ------------------------------------------------------------------
    # Generic CRUD helpers
    # ------------------------------------------------------------------

    def insert(self, collection: str, doc: dict) -> dict:
        """Insert a document, return meta (_id, _key, _rev)."""
        return self.db.collection(collection).insert(doc)

    def upsert(self, collection: str, doc: dict, key_field: str = "_key") -> dict:
        """Insert or replace by _key."""
        col = self.db.collection(collection)
        if key_field in doc and col.has(doc[key_field]):
            return col.replace(doc)
        return col.insert(doc)

    def bulk_insert_overwrite(self, collection: str, docs: list[dict]) -> dict:
        """Bulk insert documents, replacing any existing doc with the same _key.

        NOTE: do NOT use overwrite=True in import_bulk — that parameter
        truncates the entire collection before inserting, not per-document.
        We rely solely on on_duplicate='replace' for per-key conflict handling.

        Significantly faster than calling upsert() per document.
        Returns the raw import_bulk result dict.
        """
        if not docs:
            return {"inserted": 0, "errors": 0}
        col = self.db.collection(collection)
        result = col.import_bulk(docs, on_duplicate="replace")
        return result

    def get(self, collection: str, key: str) -> Optional[dict]:
        return self.db.collection(collection).get(key)

    def delete(self, collection: str, key: str) -> None:
        self.db.collection(collection).delete(key)

    def aql(self, query: str, bind_vars: Optional[dict] = None) -> list[dict]:
        """Execute an AQL query and return all results as a list."""
        cursor = self.db.aql.execute(query, bind_vars=bind_vars or {})
        return list(cursor)

    # ------------------------------------------------------------------
    # Edge helpers
    # ------------------------------------------------------------------

    def insert_edge(
        self,
        edge_collection: str,
        from_id: str,
        to_id: str,
        attributes: Optional[dict] = None,
    ) -> dict:
        """Insert an edge between two vertex IDs."""
        doc = {"_from": from_id, "_to": to_id, **(attributes or {})}
        return self.db.collection(edge_collection).insert(doc)

    # ------------------------------------------------------------------
    # Full-text & keyword search
    # ------------------------------------------------------------------

    def keyword_search(
        self, collection: str, field: str, query: str, limit: int = 20
    ) -> list[dict]:
        """Full-text keyword search on an indexed field."""
        aql = """
        FOR doc IN FULLTEXT(@collection, @field, @query)
            LIMIT @limit
            RETURN doc
        """
        return self.aql(
            aql,
            bind_vars={
                "collection": collection,
                "field": field,
                "query": query,
                "limit": limit,
            },
        )

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def traverse(
        self,
        start_vertex: str,
        graph_name: str,
        direction: str = "ANY",
        min_depth: int = 1,
        max_depth: int = 2,
        limit: int = 100,
    ) -> list[dict]:
        """Traverse a named graph from a starting vertex."""
        aql = f"""
        FOR v, e, p IN {min_depth}..{max_depth} {direction} @start
            GRAPH @graph
            OPTIONS {{uniqueVertices: 'global'}}
            LIMIT @limit
            RETURN {{vertex: v, edge: e}}
        """
        return self.aql(
            aql,
            bind_vars={
                "start": start_vertex,
                "graph": graph_name,
                "limit": limit,
            },
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        result = {}
        for name in DOCUMENT_COLLECTIONS + EDGE_COLLECTIONS:
            if self.db.has_collection(name):
                result[name] = self.db.collection(name).count()
        return result
