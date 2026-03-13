"""
Chat service - business logic for chat/AI assistant operations.
"""
from typing import List, Dict, Any, AsyncIterator
from datetime import datetime
from bson import ObjectId

from app.core.database import get_database
from app.core.config import settings
from app.clients.mcp_client import MCPClient


class ChatService:
    """Service for chat operations."""

    def __init__(self):
        self.db = get_database()
        self.sessions_collection = self.db.chat_sessions
        self.messages_collection = self.db.chat_messages

    async def send_message(
        self,
        messages: List[Dict[str, str]],
        session_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Send message and get AI response."""
        is_new_session = not session_id
        if is_new_session:
            # Extract title from first user message
            first_user_msg = next((m for m in messages if m.get("role") == "user"), None)
            title = ""
            if first_user_msg:
                title = first_user_msg.get("content", "").strip()[:60]
            session_id = await self._create_session(user_id, title)

        # Store user message
        user_message = messages[-1]
        await self._store_message(session_id, user_message)

        # Get AI response from MCP server
        if settings.MCP_SERVER_ENABLED:
            ai_response = await self._get_mcp_response(messages)
        else:
            ai_response = {
                "role": "assistant",
                "content": "MCP server is not enabled. This is a placeholder response."
            }

        # Store AI response
        await self._store_message(session_id, ai_response)
        await self._touch_session(session_id)

        return {
            "message": ai_response,
            "session_id": session_id
        }

    async def process_message_stream(
        self,
        session_id: str,
        message: str,
        user_id: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream chat events for the WebSocket endpoint.

        Yields event dicts:
          {"type": "agent_activity", "agent": "...", "status": "working", "task": "..."}
          {"type": "message", "role": "assistant", "content": "...", "session_id": "..."}
        """
        # Ensure session exists
        if not session_id or session_id == "new":
            session_id = await self._create_session(user_id, message[:60])

        user_msg = {"role": "user", "content": message}
        await self._store_message(session_id, user_msg)

        if not settings.MCP_SERVER_ENABLED:
            ai_response = {
                "role": "assistant",
                "content": "MCP server is not enabled. This is a placeholder response.",
            }
            await self._store_message(session_id, ai_response)
            await self._touch_session(session_id)
            yield {"type": "message", **ai_response, "session_id": session_id}
            return

        mcp = MCPClient()
        final_content = ""

        async for event in mcp.stream_tool_call(
            tool_name="chat",
            arguments={"message": message, "session_id": session_id},
        ):
            event_type = event.get("type")

            if event_type == "agent_activity":
                yield event
            elif event_type == "partial_result":
                final_content += event.get("text", "")
                yield event
            elif event_type == "final_result":
                final_content = event.get("answer", final_content)
                ai_response = {"role": "assistant", "content": final_content}
                await self._store_message(session_id, ai_response)
                await self._touch_session(session_id)
                yield {"type": "message", **ai_response, "session_id": session_id}
            elif event_type == "error":
                yield event

    async def _get_mcp_response(self, messages: List[Dict[str, str]]) -> Dict[str, str]:
        """Get response from MCP server (used by REST endpoint)."""
        mcp = MCPClient()
        return await mcp.chat(messages)

    async def _touch_session(self, session_id: str) -> None:
        """Update session updated_at timestamp."""
        await self.sessions_collection.update_one(
            {"_id": ObjectId(session_id)},
            {"$set": {"updated_at": datetime.utcnow()}},
        )

    async def _create_session(self, user_id: str, title: str = "") -> str:
        """Create new chat session."""
        now = datetime.utcnow()
        session_data = {
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now
        }
        result = await self.sessions_collection.insert_one(session_data)
        return str(result.inserted_id)

    async def _store_message(self, session_id: str, message: Dict[str, str]):
        """Store message in database."""
        message_data = {
            "session_id": session_id,
            "role": message["role"],
            "content": message["content"],
            "timestamp": datetime.utcnow()
        }
        await self.messages_collection.insert_one(message_data)

    async def list_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """List user's chat sessions."""
        cursor = self.sessions_collection.find(
            {"user_id": user_id},
            {"_id": 1, "title": 1, "created_at": 1, "updated_at": 1}
        ).sort("updated_at", -1)
        sessions = []
        async for session in cursor:
            sessions.append({
                "id": str(session["_id"]),
                "title": session.get("title", ""),
                "created_at": session.get("created_at"),
                "updated_at": session.get("updated_at")
            })
        return sessions

    async def get_session(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Get chat session with messages."""
        session = await self.sessions_collection.find_one({
            "_id": ObjectId(session_id),
            "user_id": user_id
        })

        if not session:
            return None

        # Get messages
        cursor = self.messages_collection.find({"session_id": session_id}).sort("timestamp", 1)
        messages = []
        async for msg in cursor:
            messages.append({
                "id": str(msg["_id"]),
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": msg.get("timestamp")
            })

        return {
            "id": str(session["_id"]),
            "title": session.get("title", ""),
            "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
            "messages": messages
        }

    async def rename_session(self, session_id: str, user_id: str, title: str) -> bool:
        """Rename a chat session."""
        result = await self.sessions_collection.update_one(
            {"_id": ObjectId(session_id), "user_id": user_id},
            {"$set": {"title": title, "updated_at": datetime.utcnow()}}
        )
        return result.matched_count > 0
