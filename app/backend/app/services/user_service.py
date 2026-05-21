"""
User service - business logic for user management.
"""
from datetime import datetime, timezone
from typing import List, Optional

import bcrypt
from bson import ObjectId
from fastapi import HTTPException, status

from app.core.auth import get_password_hash, verify_password
from app.core.database import get_database
from app.models.user import User, UserCreate, UserUpdate


# Precomputed dummy bcrypt hash used to keep authenticate_user's timing
# constant regardless of whether the email exists. Computed once at import time.
_DUMMY_BCRYPT_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt()).decode()

# Roles accepted by assign_role / remove_role.
VALID_ROLES = frozenset({"administrator", "knowledge_curator", "knowledge_explorator"})


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
        """Get existing user or create new one (Google OAuth flow)."""
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
                update_fields["updated_at"] = datetime.now(timezone.utc)
                await self.collection.update_one(
                    {"_id": user_doc["_id"]},
                    {"$set": update_fields}
                )
                user_doc.update(update_fields)

            user_doc["_id"] = str(user_doc["_id"])
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
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }

        result = await self.collection.insert_one(new_user)
        new_user["_id"] = str(result.inserted_id)
        return User(**new_user)

    async def create_native_user(
        self,
        email: str,
        full_name: Optional[str],
        password: str,
        roles: List[str]
    ) -> User:
        """Create a new native (email/password) user. Admin only."""
        existing = await self.collection.find_one({"email": email})
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists"
            )

        new_user = {
            "email": email,
            "full_name": full_name,
            "password_hash": get_password_hash(password),
            "roles": roles,
            "capabilities": [],
            "status": "active",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }

        result = await self.collection.insert_one(new_user)
        new_user["_id"] = str(result.inserted_id)
        return User(**new_user)

    async def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Verify email/password credentials. Returns User on success, None on failure.

        Always runs bcrypt verification (against a dummy hash if no user / no
        password_hash) to avoid leaking user existence via response timing.
        """
        user_doc = await self.collection.find_one({"email": email})
        password_hash = user_doc.get("password_hash") if user_doc else None

        if not password_hash:
            # Run verify against a dummy hash to equalise timing, then fail.
            verify_password(password, _DUMMY_BCRYPT_HASH)
            return None

        if not verify_password(password, password_hash):
            return None

        user_doc["_id"] = str(user_doc["_id"])
        return User(**user_doc)

    async def set_password(self, user_id: str, new_password: str) -> None:
        """Hash and store a new password for a user."""
        await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "password_hash": get_password_hash(new_password),
                "updated_at": datetime.now(timezone.utc)
            }}
        )

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
        update_data["updated_at"] = datetime.now(timezone.utc)

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
        if role not in VALID_ROLES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown role: {role!r}",
            )
        await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$addToSet": {"roles": role},
                "$set": {"updated_at": datetime.now(timezone.utc)}
            }
        )
        return await self.get_user_by_id(user_id)

    async def remove_role(self, user_id: str, role: str) -> User:
        """Remove role from user."""
        if role not in VALID_ROLES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown role: {role!r}",
            )
        await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$pull": {"roles": role},
                "$set": {"updated_at": datetime.now(timezone.utc)}
            }
        )
        return await self.get_user_by_id(user_id)
