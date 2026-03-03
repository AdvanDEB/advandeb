"""
MongoDB connection management.

Provides:
- `mongodb` singleton — async Motor connection for FastAPI / asyncio code
- `get_sync_db()` — synchronous PyMongo database for Celery tasks
"""
import logging

import pymongo
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from advandeb_kb.config.settings import settings

logger = logging.getLogger(__name__)


class MongoDB:
    """Async Motor connection holder used by FastAPI / asyncio services."""

    def __init__(self):
        self.client: AsyncIOMotorClient = None
        self.database: AsyncIOMotorDatabase = None

    async def connect(self):
        try:
            self.client = AsyncIOMotorClient(settings.MONGODB_URL)
            self.database = self.client[settings.DATABASE_NAME]
            await self.client.admin.command("ping")
            logger.info("Connected to MongoDB (async)")
        except Exception:
            logger.exception("Failed to connect to MongoDB")
            raise

    async def disconnect(self):
        if self.client:
            self.client.close()
            self.client = None
            self.database = None
            logger.info("Disconnected from MongoDB (async)")


mongodb = MongoDB()


# ---------------------------------------------------------------------------
# Legacy helpers (kept for backwards compatibility with existing FastAPI code)
# ---------------------------------------------------------------------------

async def connect_to_mongo():
    await mongodb.connect()


async def close_mongo_connection():
    await mongodb.disconnect()


async def get_database() -> AsyncIOMotorDatabase:
    return mongodb.database


# ---------------------------------------------------------------------------
# Synchronous accessor for Celery tasks
# ---------------------------------------------------------------------------

_sync_client: pymongo.MongoClient = None


def get_sync_db() -> pymongo.database.Database:
    """Return a synchronous PyMongo database instance.

    The client is created once and reused.  Safe to call from Celery tasks
    (which run in a regular synchronous context without an event loop).
    """
    global _sync_client
    if _sync_client is None:
        _sync_client = pymongo.MongoClient(settings.MONGODB_URL)
        logger.info("Created synchronous PyMongo client")
    return _sync_client[settings.DATABASE_NAME]
