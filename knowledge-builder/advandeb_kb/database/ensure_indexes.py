"""
ensure_indexes — idempotent MongoDB index creation for KB graph collections.

Call ``ensure_kb_indexes(db)`` once at application startup (after the database
connection is established) to guarantee that all performance-critical indexes
exist on ``graph_nodes`` and ``graph_edges``.

All indexes are created with ``background=True`` so they don't block the event
loop on first startup against a collection that already contains documents.
"""
import logging

logger = logging.getLogger(__name__)


async def ensure_kb_indexes(db) -> None:
    """Create (or confirm existence of) all required KB graph indexes.

    Parameters
    ----------
    db:
        A Motor (AsyncIOMotorDatabase) or PyMongo database instance that
        exposes ``graph_nodes`` and ``graph_edges`` collections.
    """
    # ------------------------------------------------------------------
    # graph_nodes indexes
    # ------------------------------------------------------------------
    await db.graph_nodes.create_index(
        [("schema_id", 1)],
        background=True,
        name="graph_nodes_schema_id",
    )
    await db.graph_nodes.create_index(
        [("schema_id", 1), ("node_type", 1)],
        background=True,
        name="graph_nodes_schema_node_type",
    )
    await db.graph_nodes.create_index(
        [("schema_id", 1), ("degree", -1)],
        background=True,
        name="graph_nodes_schema_degree",
    )

    # ------------------------------------------------------------------
    # graph_edges indexes
    # ------------------------------------------------------------------
    await db.graph_edges.create_index(
        [("schema_id", 1)],
        background=True,
        name="graph_edges_schema_id",
    )
    await db.graph_edges.create_index(
        [("schema_id", 1), ("source_node_id", 1)],
        background=True,
        name="graph_edges_schema_source",
    )
    await db.graph_edges.create_index(
        [("schema_id", 1), ("target_node_id", 1)],
        background=True,
        name="graph_edges_schema_target",
    )

    logger.info(
        "ensure_kb_indexes: all graph_nodes and graph_edges indexes verified/created"
    )
