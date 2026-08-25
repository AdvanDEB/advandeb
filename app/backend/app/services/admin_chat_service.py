"""
Admin chat service — read-only staff access to another user's chat history.

AdvanDEB is a research project; users consent to staff reviewing their chat
history for research purposes, with a per-user self-service opt-out
(``User.chat_history_visible_to_admin``). Every admin read is logged to the
``chat_access_log`` collection so a user can see who from staff has looked at
their conversations (``GET /api/users/me/chat-access-log``).

Session/message reads are delegated to the existing ``ChatService`` — its
methods already take an arbitrary ``user_id`` rather than assuming "the
caller", so admin access is just calling them with the *target* user's id.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.core.database import get_database
from app.models.user import User
from app.services.chat_service import ChatService


class AdminChatService:
    """Admin-only wrapper around ChatService with consent checks + audit logging."""

    def __init__(self):
        self.db = get_database()
        self.access_log = self.db.chat_access_log
        self.chat_service = ChatService()

    @staticmethod
    def _check_opt_out(target: User) -> None:
        if not target.chat_history_visible_to_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This user has opted out of staff chat access",
            )

    async def _log_access(
        self, admin: dict, target: User, session_id: Optional[str]
    ) -> None:
        await self.access_log.insert_one({
            "admin_id": admin["id"],
            "admin_email": admin.get("email"),
            "target_user_id": target.id,
            "target_email": target.email,
            "session_id": session_id,
            "accessed_at": datetime.now(timezone.utc),
        })

    async def list_sessions_as_admin(
        self, admin: dict, target: User
    ) -> List[Dict[str, Any]]:
        """List a user's chat sessions on behalf of an admin. Logs the access."""
        self._check_opt_out(target)
        sessions = await self.chat_service.list_sessions(target.id)
        await self._log_access(admin, target, session_id=None)
        return sessions

    async def get_session_as_admin(
        self, admin: dict, target: User, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch one of a user's sessions (with messages) on behalf of an admin."""
        self._check_opt_out(target)
        session = await self.chat_service.get_session(session_id, target.id)
        if session:
            await self._log_access(admin, target, session_id=session_id)
        return session

    async def list_access_log(self, target_user_id: str) -> List[Dict[str, Any]]:
        """List past admin accesses to a user's chat history, most recent first."""
        cursor = self.access_log.find(
            {"target_user_id": target_user_id}
        ).sort("accessed_at", -1)
        entries = []
        async for doc in cursor:
            entries.append({
                "admin_email": doc.get("admin_email"),
                "session_id": doc.get("session_id"),
                "accessed_at": doc.get("accessed_at"),
            })
        return entries
