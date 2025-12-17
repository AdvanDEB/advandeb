"""
User service - business logic for user management.
"""
from datetime import datetime
from typing import List, Optional
from bson import ObjectId

from app.core.database import get_database
from app.models.user import User, UserCreate, UserUpdate


class UserService:
    """Service for user operations."""
    
    def __init__(self):
        self.db = get_database()
        self.collection = self.db.users
    
    async def get_or_create_user(
        self,
        google_id: str,
        email: str,
        full_name: Optional[str] = None,
        avatar_url: Optional[str] = None
    ) -> User:
        """Get existing user or create new one."""
        # Try to find existing user
        user_doc = await self.collection.find_one({"google_id": google_id})
        
        if user_doc:
            # Update avatar and name if changed
            update_fields = {}
            if full_name and user_doc.get("full_name") != full_name:
                update_fields["full_name"] = full_name
            if avatar_url and user_doc.get("avatar_url") != avatar_url:
                update_fields["avatar_url"] = avatar_url
            
            if update_fields:
                update_fields["updated_at"] = datetime.utcnow()
                await self.collection.update_one(
                    {"_id": user_doc["_id"]},
                    {"$set": update_fields}
                )
                user_doc.update(update_fields)
            
            return User(**user_doc)
        
        # Create new user
        new_user = {
            "google_id": google_id,
            "email": email,
            "full_name": full_name,
            "avatar_url": avatar_url,
            "roles": ["knowledge_explorator"],  # Default role
            "capabilities": [],
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = await self.collection.insert_one(new_user)
        new_user["_id"] = str(result.inserted_id)
        return User(**new_user)
    
    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        user_doc = await self.collection.find_one({"_id": ObjectId(user_id)})
        if user_doc:
            user_doc["_id"] = str(user_doc["_id"])
            return User(**user_doc)
        return None
    
    async def update_user(self, user_id: str, user_update: UserUpdate) -> User:
        """Update user profile."""
        update_data = user_update.model_dump(exclude_unset=True)
        update_data["updated_at"] = datetime.utcnow()
        
        await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )
        
        return await self.get_user_by_id(user_id)
    
    async def list_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """List all users."""
        cursor = self.collection.find().skip(skip).limit(limit)
        users = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            users.append(User(**doc))
        return users
    
    async def assign_role(self, user_id: str, role: str) -> User:
        """Assign role to user."""
        await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$addToSet": {"roles": role},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        return await self.get_user_by_id(user_id)
    
    async def remove_role(self, user_id: str, role: str) -> User:
        """Remove role from user."""
        await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$pull": {"roles": role},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        return await self.get_user_by_id(user_id)
