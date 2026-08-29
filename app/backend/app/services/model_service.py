"""
Model service - business logic for model management.
"""
from datetime import datetime, timezone
from typing import List, Optional
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

from app.core.database import get_database
from app.models.scenario import Model, ModelCreate


class ModelService:
    """Service for model operations."""
    
    def __init__(self):
        self.db = get_database()
        self.collection = self.db.models
    
    async def create_model(self, model: ModelCreate, creator_id: str) -> Model:
        """Create a new model."""
        model_data = model.model_dump()
        model_data.update({
            "creator_id": creator_id,
            "status": "draft",
            "version": 1,
            "provenance": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })
        
        result = await self.collection.insert_one(model_data)
        model_data["_id"] = str(result.inserted_id)
        return Model(**model_data)
    
    async def get_model(self, model_id: str) -> Optional[Model]:
        """Get model by ID."""
        try:
            oid = ObjectId(model_id)
        except (InvalidId, TypeError):
            return None
        model_doc = await self.collection.find_one({"_id": oid})
        if model_doc:
            model_doc["_id"] = str(model_doc["_id"])
            return Model(**model_doc)
        return None
    
    async def list_models(
        self,
        skip: int = 0,
        limit: int = 100,
        scenario_id: Optional[str] = None
    ) -> List[Model]:
        """List models, optionally filtered by scenario."""
        query = {}
        if scenario_id:
            query["scenario_id"] = scenario_id
        
        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        models = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            models.append(Model(**doc))
        return models
    
    async def update_model(
        self,
        model_id: str,
        model_update: ModelCreate,
        user_id: str,
        is_admin: bool = False
    ) -> Optional[Model]:
        """Update model with ownership check."""
        try:
            oid = ObjectId(model_id)
        except (InvalidId, TypeError):
            return None

        model_doc = await self.collection.find_one({"_id": oid})
        if not model_doc:
            return None

        if model_doc.get("creator_id") != user_id and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to modify this model"
            )

        update_data = model_update.model_dump()
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        # Increment version on update
        await self.collection.update_one(
            {"_id": oid},
            {
                "$set": update_data,
                "$inc": {"version": 1}
            }
        )
        
        return await self.get_model(model_id)
    
    async def delete_model(
        self,
        model_id: str,
        user_id: str,
        is_admin: bool = False
    ) -> bool:
        """Delete model with ownership check."""
        try:
            oid = ObjectId(model_id)
        except (InvalidId, TypeError):
            return False

        model_doc = await self.collection.find_one({"_id": oid})
        if not model_doc:
            return False

        if model_doc.get("creator_id") != user_id and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this model"
            )

        result = await self.collection.delete_one({"_id": oid})
        return result.deleted_count > 0
