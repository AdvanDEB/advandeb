"""
Database connection management.

Three data stores:
  MongoDB (advandeb)            : users, auth, chat sessions/messages,
                                  user submissions, scenarios, models
  MongoDB (advandeb_kb)         : KB workflow/runtime metadata
                                  (ingestion_batches, ingestion_jobs,
                                   graph_artifact_meta)
  ArangoDB (advandeb_kb)        : all KB knowledge data — documents, facts,
                                  stylized_facts, taxa, chunks, graph edges,
                                  provenance traces

Public API:
  connect_to_mongo() / close_mongo_connection()  — called from lifespan
  get_database()      → app MongoDB (advandeb)
  get_kb_database()   → KB MongoDB (ingestion workflow state only)
  get_arango_db()     → ArangoDB KB client (all KB reads/writes)
  ensure_app_indexes() — called from lifespan to set up submission indexes
"""
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------

class Database:
    client: Optional[AsyncIOMotorClient] = None


db = Database()


async def connect_to_mongo():
    """Connect to MongoDB."""
    db.client = AsyncIOMotorClient(
        settings.MONGODB_URI,
        maxPoolSize=settings.MONGO_MAX_POOL_SIZE,
    )
    logger.info("Connected to MongoDB at %s", settings.MONGODB_URI)


async def close_mongo_connection():
    """Close MongoDB connection."""
    if db.client:
        db.client.close()
        logger.info("Closed MongoDB connection")


def get_database():
    """Return the app MongoDB database (advandeb)."""
    return db.client[settings.MONGODB_DB_NAME]


def get_kb_database():
    """Return the KB MongoDB database (advandeb_knowledge_builder_kb).

    Used for KB workflow/runtime metadata such as ingestion state and
    graph artifact metadata.
    All KB knowledge data (documents, facts, taxa, etc.) lives in ArangoDB.
    """
    return db.client[settings.KB_DB_NAME]


# ---------------------------------------------------------------------------
# ArangoDB — KB primary store
# ---------------------------------------------------------------------------

_arango_db = None


def get_arango_db():
    """Return a connected ArangoDB database handle (python-arango synchronous client).

    The client is created once and reused.  Thread-safe for read-only queries;
    writes from async code should be dispatched via run_in_executor.
    """
    global _arango_db
    if _arango_db is None:
        from advandeb_kb.database.arango_client import ArangoDatabase

        client = ArangoDatabase(
            url=settings.ARANGO_URL,
            db_name=settings.ARANGO_DB_NAME,
            username=settings.ARANGO_USERNAME,
            password=settings.ARANGO_PASSWORD,
        )
        client.connect()
        _arango_db = client
        logger.info(
            "Connected to ArangoDB at %s / %s",
            settings.ARANGO_URL,
            settings.ARANGO_DB_NAME,
        )
    return _arango_db


# ---------------------------------------------------------------------------
# App MongoDB indexes
# ---------------------------------------------------------------------------

async def ensure_app_indexes(app_db) -> None:
    """Create indexes on the app MongoDB submission collections.

    Idempotent — safe to call on every startup.
    """
    # document_submissions
    await app_db.document_submissions.create_index(
        [("uploader_id", 1), ("created_at", -1)],
        background=True,
        name="doc_sub_uploader_created",
    )
    await app_db.document_submissions.create_index(
        [("status", 1), ("created_at", -1)],
        background=True,
        name="doc_sub_status_created",
    )
    await app_db.document_submissions.create_index(
        [("title", "text")],
        background=True,
        name="doc_sub_title_text",
    )

    # fact_submissions
    await app_db.fact_submissions.create_index(
        [("creator_id", 1), ("created_at", -1)],
        background=True,
        name="fact_sub_creator_created",
    )
    await app_db.fact_submissions.create_index(
        [("status", 1), ("created_at", -1)],
        background=True,
        name="fact_sub_status_created",
    )

    # sf_submissions
    await app_db.sf_submissions.create_index(
        [("creator_id", 1), ("created_at", -1)],
        background=True,
        name="sf_sub_creator_created",
    )
    await app_db.sf_submissions.create_index(
        [("status", 1), ("created_at", -1)],
        background=True,
        name="sf_sub_status_created",
    )

    logger.info("ensure_app_indexes: submission collection indexes verified/created")
