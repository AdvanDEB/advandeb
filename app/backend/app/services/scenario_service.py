"""
Scenario service - business logic for scenario management.
"""
from datetime import datetime, timezone
from typing import List, Optional
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

from app.core.database import get_database
from app.models.scenario import Scenario, ScenarioCreate


class ScenarioService:
    """Service for scenario operations."""
    
    def __init__(self):
        self.db = get_database()
        self.collection = self.db.scenarios
    
    async def create_scenario(
        self,
        scenario: ScenarioCreate,
        creator_id: str
    ) -> Scenario:
        """Create a new scenario."""
        scenario_data = scenario.model_dump()
        scenario_data.update({
            "creator_id": creator_id,
            "status": "draft",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })
        
        result = await self.collection.insert_one(scenario_data)
        scenario_data["_id"] = str(result.inserted_id)
        return Scenario(**scenario_data)
    
    async def get_scenario(self, scenario_id: str) -> Optional[Scenario]:
        """Get scenario by ID."""
        try:
            oid = ObjectId(scenario_id)
        except (InvalidId, TypeError):
            return None
        scenario_doc = await self.collection.find_one({"_id": oid})
        if scenario_doc:
            scenario_doc["_id"] = str(scenario_doc["_id"])
            return Scenario(**scenario_doc)
        return None
    
    async def list_scenarios(
        self,
        skip: int = 0,
        limit: int = 100
    ) -> List[Scenario]:
        """List scenarios."""
        cursor = self.collection.find().skip(skip).limit(limit).sort("created_at", -1)
        scenarios = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            scenarios.append(Scenario(**doc))
        return scenarios
    
    async def update_scenario(
        self,
        scenario_id: str,
        scenario_update: ScenarioCreate,
        user_id: str,
        is_admin: bool = False
    ) -> Optional[Scenario]:
        """Update scenario with ownership check."""
        try:
            oid = ObjectId(scenario_id)
        except (InvalidId, TypeError):
            return None

        scenario_doc = await self.collection.find_one({"_id": oid})
        if not scenario_doc:
            return None

        if scenario_doc.get("creator_id") != user_id and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to modify this scenario"
            )

        update_data = scenario_update.model_dump()
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        await self.collection.update_one(
            {"_id": oid},
            {"$set": update_data}
        )
        
        return await self.get_scenario(scenario_id)
    
    async def delete_scenario(
        self,
        scenario_id: str,
        user_id: str,
        is_admin: bool = False
    ) -> bool:
        """Delete scenario with ownership check."""
        try:
            oid = ObjectId(scenario_id)
        except (InvalidId, TypeError):
            return False

        scenario_doc = await self.collection.find_one({"_id": oid})
        if not scenario_doc:
            return False

        if scenario_doc.get("creator_id") != user_id and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this scenario"
            )

        result = await self.collection.delete_one({"_id": oid})
        return result.deleted_count > 0
