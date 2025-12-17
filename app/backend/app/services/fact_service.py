"""
Fact service - business logic for fact management.
"""
from datetime import datetime
from typing import List, Optional
from bson import ObjectId

from app.core.database import get_database
from app.models.fact import Fact, FactCreate, StylizedFact, StylizedFactCreate


class FactService:
    """Service for fact operations."""
    
    def __init__(self):
        self.db = get_database()
        self.facts_collection = self.db.facts
        self.stylized_facts_collection = self.db.stylized_facts
    
    async def create_fact(self, fact: FactCreate, creator_id: str) -> Fact:
        """Create a new fact."""
        fact_data = fact.model_dump()
        fact_data.update({
            "creator_id": creator_id,
            "status": "pending_review",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })
        
        result = await self.facts_collection.insert_one(fact_data)
        fact_data["_id"] = str(result.inserted_id)
        return Fact(**fact_data)
    
    async def get_fact(self, fact_id: str) -> Optional[Fact]:
        """Get fact by ID."""
        fact_doc = await self.facts_collection.find_one({"_id": ObjectId(fact_id)})
        if fact_doc:
            fact_doc["_id"] = str(fact_doc["_id"])
            return Fact(**fact_doc)
        return None
    
    async def list_facts(
        self,
        skip: int = 0,
        limit: int = 100,
        status_filter: Optional[str] = None
    ) -> List[Fact]:
        """List facts with optional status filter."""
        query = {}
        if status_filter:
            query["status"] = status_filter
        
        cursor = self.facts_collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        facts = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            facts.append(Fact(**doc))
        return facts
    
    async def create_stylized_fact(
        self,
        stylized_fact: StylizedFactCreate,
        creator_id: str
    ) -> StylizedFact:
        """Create a stylized fact."""
        sf_data = stylized_fact.model_dump()
        sf_data.update({
            "creator_id": creator_id,
            "status": "pending_review",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })
        
        result = await self.stylized_facts_collection.insert_one(sf_data)
        sf_data["_id"] = str(result.inserted_id)
        return StylizedFact(**sf_data)
    
    async def list_stylized_facts(
        self,
        skip: int = 0,
        limit: int = 100
    ) -> List[StylizedFact]:
        """List stylized facts."""
        cursor = self.stylized_facts_collection.find().skip(skip).limit(limit).sort("created_at", -1)
        stylized_facts = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            stylized_facts.append(StylizedFact(**doc))
        return stylized_facts
