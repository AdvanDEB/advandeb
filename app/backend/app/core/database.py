"""
Database connection management.
"""
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional

from app.core.config import settings


class Database:
    client: Optional[AsyncIOMotorClient] = None
    

db = Database()


async def connect_to_mongo():
    """Connect to MongoDB."""
    db.client = AsyncIOMotorClient(settings.MONGODB_URI)
    print(f"Connected to MongoDB at {settings.MONGODB_URI}")


async def close_mongo_connection():
    """Close MongoDB connection."""
    if db.client:
        db.client.close()
        print("Closed MongoDB connection")


def get_database():
    """Get database instance."""
    return db.client[settings.MONGODB_DB_NAME]


def get_kb_database():
    """Get the Knowledge Builder database instance (advandeb_knowledge_builder_kb)."""
    return db.client[settings.KB_DB_NAME]
