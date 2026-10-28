"""
User service - business logic for user management.
"""
import re
import secrets
import string
from datetime import datetime, timezone
from typing import List, Optional

import bcrypt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.core.auth import ROLE_EXTERNAL_CONTRIBUTOR, get_password_hash, revoke_all_sessions, verify_password
from app.core.database import EMAIL_COLLATION, get_database
from app.models.user import User, UserCreate, UserUpdate, normalize_email


# Precomputed dummy bcrypt hash used to keep authenticate_user's timing
# constant regardless of whether the email exists. Computed once at import time.
_DUMMY_BCRYPT_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt()).decode()

# Roles accepted by create_native_user / assign_role / remove_role.
VALID_ROLES = frozenset({
    "administrator", "knowledge_curator", "knowledge_explorator",
    ROLE_EXTERNAL_CONTRIBUTOR,
})

# Statuses accepted by set_status.
VALID_STATUSES = frozenset({"active", "suspended"})

# Excludes visually ambiguous characters (0/O, 1/l/I).
_PASSWORD_ALPHABET = (
    string.ascii_uppercase.replace("O", "").replace("I", "")
    + string.ascii_lowercase.replace("l", "").replace("o", "")
    + string.digits.replace("0", "").replace("1", "")
    + "!@#%*+-="
)


def generate_password(length: int = 14) -> str:
    """Generate a strong random password for account creation/reset."""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def _validate_roles(roles: List[str]) -> List[str]:
    unknown = sorted(set(roles) - VALID_ROLES)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown role(s): {', '.join(unknown)}")
    if not roles:
        raise HTTPException(status_code=422, detail="A user needs at least one role")
    # De-duplicate, keeping the caller's order.
    return list(dict.fromkeys(roles))


class UserService:
    """Service for user operations."""

    def __init__(self):
        self.db = get_database()
        self.collection = self.db.users

    async def find_by_email(self, email: str) -> Optional[dict]:
        """Find a user document by email, ignoring case.

        New addresses are stored normalised (see ``normalize_email``); the
        case-insensitive collation also finds accounts stored before that, and
        is the one the unique index is built with, so the lookup can use it.
        """
        return await self.collection.find_one(
            {"email": normalize_email(email)}, collation=EMAIL_COLLATION)

    async def get_google_user(
        self,
        google_id: str,
        email: str,
        email_verified: bool,
        full_name: Optional[str] = None,
        avatar_url: Optional[str] = None
    ) -> User:
        """Resolve a Google sign-in to an existing account. Never creates one.

        Registration is by invitation: an administrator creates the account,
        or approves an enrolment request, and Google sign-in then works for
        it. The first Google sign-in links the Google identity to the account
        whose address Google has verified; later ones find it by ``google_id``.
        Anyone else gets a 403 — this used to hand every Google user on earth
        an explorator account, with read access to licensed full text.
        """
        user_doc = await self.collection.find_one({"google_id": google_id})

        if user_doc is None:
            not_invited = HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No AdvanDEB account for this Google address. "
                       "Ask an administrator for an invitation.",
            )
            if not email_verified:
                raise not_invited
            user_doc = await self.find_by_email(email)
            # An account already linked to a *different* Google identity is
            # not this caller's to claim, whatever the address says.
            if user_doc is None or user_doc.get("google_id") not in (None, google_id):
                raise not_invited
            await self.collection.update_one(
                {"_id": user_doc["_id"]}, {"$set": {"google_id": google_id}})
            user_doc["google_id"] = google_id

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

    async def create_native_user(
        self,
        email: str,
        full_name: Optional[str],
        password: str,
        roles: List[str]
    ) -> User:
        """Create a new native (email/password) user. Admin only."""
        email = normalize_email(email)
        roles = _validate_roles(roles)
        if await self.find_by_email(email):
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

        try:
            result = await self.collection.insert_one(new_user)
        except DuplicateKeyError:
            # Lost a race with a concurrent create; the unique index decided.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists"
            )
        new_user["_id"] = str(result.inserted_id)
        return User(**new_user)

    async def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Verify email/password credentials. Returns User on success, None on failure.

        Always runs bcrypt verification (against a dummy hash if no user / no
        password_hash) to avoid leaking user existence via response timing.
        """
        user_doc = await self.find_by_email(email)
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
        """Hash and store a new password, ending every existing session.

        Whoever knew the old password may hold a refresh token minted with it;
        a password change that leaves those working has not locked them out.
        """
        await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "password_hash": get_password_hash(new_password),
                "updated_at": datetime.now(timezone.utc)
            }}
        )
        await revoke_all_sessions(user_id)

    async def change_own_password(
        self, user_id: str, new_password: str, current_password: Optional[str]
    ) -> None:
        """Self-service password change; the current password must be proven.

        An account with no password yet (created through Google sign-in) may
        set one without it — there is nothing to prove.
        """
        user_doc = await self.collection.find_one({"_id": ObjectId(user_id)})
        if user_doc is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        existing_hash = user_doc.get("password_hash")
        if existing_hash and not (
                current_password and verify_password(current_password, existing_hash)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Current password is incorrect",
            )
        await self.set_password(user_id, new_password)

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID; None for an unknown or malformed id."""
        try:
            oid = ObjectId(user_id)
        except (InvalidId, TypeError):
            return None
        user_doc = await self.collection.find_one({"_id": oid})
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

    @staticmethod
    def _build_filter(
        q: Optional[str] = None,
        role: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> dict:
        """Build a Mongo filter for list_users / count_users."""
        filt: dict = {}
        if q:
            escaped_q = re.escape(q)
            filt["$or"] = [
                {"email": {"$regex": escaped_q, "$options": "i"}},
                {"full_name": {"$regex": escaped_q, "$options": "i"}},
            ]
        if role:
            filt["roles"] = role
        if status_filter:
            filt["status"] = status_filter
        return filt

    async def list_users(
        self,
        skip: int = 0,
        limit: int = 100,
        q: Optional[str] = None,
        role: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> List[User]:
        """List users, optionally filtered by email/name search, role, or status."""
        filt = self._build_filter(q, role, status_filter)
        cursor = self.collection.find(filt).skip(skip).limit(limit)
        users = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            users.append(User(**doc))
        return users

    async def count_users(
        self,
        q: Optional[str] = None,
        role: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> int:
        """Count users matching the same filter as list_users."""
        filt = self._build_filter(q, role, status_filter)
        return await self.collection.count_documents(filt)

    async def set_status(self, user_id: str, new_status: str) -> Optional[User]:
        """Change a user's account status (active/suspended). Admin only."""
        if new_status not in VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown status: {new_status!r}",
            )
        result = await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc)}}
        )
        if result.matched_count == 0:
            return None
        if new_status == "suspended":
            # The status check already refuses every token while suspended;
            # revoking too means reactivation does not revive old sessions.
            await revoke_all_sessions(user_id)
        return await self.get_user_by_id(user_id)

    async def delete_user(self, user_id: str) -> bool:
        """Permanently delete a user and their private data. Admin only.

        Cascades to everything that is *the user's own*: encrypted provider
        keys, chat sessions and their messages, in-flight OAuth state, and the
        staff-access log describing reads of their chats. Knowledge
        contributions (document/fact/SF submissions, ingestion jobs) are
        deliberately preserved — they are attributed research output, and the
        graph would lose provenance if a departing curator's facts vanished.

        Returns True if a user was removed.
        """
        result = await self.collection.delete_one({"_id": ObjectId(user_id)})
        if result.deleted_count == 0:
            return False

        # Chat messages are keyed by session_id only, so the session ids have
        # to be collected before the sessions themselves are removed.
        session_ids = [
            str(doc["_id"])
            async for doc in self.db.chat_sessions.find({"user_id": user_id}, {"_id": 1})
        ]
        if session_ids:
            await self.db.chat_messages.delete_many({"session_id": {"$in": session_ids}})
        await self.db.chat_sessions.delete_many({"user_id": user_id})
        await self.db.user_llm_keys.delete_many({"user_id": user_id})
        await self.db.user_oauth_flows.delete_many({"user_id": user_id})
        await self.db.chat_access_log.delete_many({"target_user_id": user_id})
        return True

    async def admin_reset_password(self, user_id: str) -> Optional[str]:
        """Generate and store a new password for a user. Returns the plaintext once."""
        existing = await self.get_user_by_id(user_id)
        if not existing:
            return None
        new_password = generate_password()
        await self.set_password(user_id, new_password)
        return new_password

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
