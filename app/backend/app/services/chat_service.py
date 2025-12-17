"""
Chat service - business logic for chat/AI assistant operations.
"""
from typing import List, Dict, Any
from datetime import datetime
from bson import ObjectId
import httpx

from app.core.database import get_database
from app.core.config import settings


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
        # Create or get session
        if not session_id:
            session_id = await self._create_session(user_id)
        
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
        
        return {
            "message": ai_response,
            "session_id": session_id
        }
    
    async def _get_mcp_response(self, messages: List[Dict[str, str]]) -> Dict[str, str]:
        """Get response from MCP server."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.MCP_SERVER_URL}/chat",
                    json={"messages": messages},
                    timeout=30.0
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("message", {})
        except Exception as e:
            print(f"Error calling MCP server: {e}")
        
        return {
            "role": "assistant",
            "content": "Sorry, I'm having trouble connecting to the AI service."
        }
    
    async def _create_session(self, user_id: str) -> str:
        """Create new chat session."""
        session_data = {
            "user_id": user_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
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
        cursor = self.sessions_collection.find({"user_id": user_id}).sort("updated_at", -1)
        sessions = []
        async for session in cursor:
            session["_id"] = str(session["_id"])
            sessions.append(session)
        return sessions
    
    async def get_session(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Get chat session with messages."""
        session = await self.sessions_collection.find_one({
            "_id": ObjectId(session_id),
            "user_id": user_id
        })
        
        if not session:
            return None
        
        session["_id"] = str(session["_id"])
        
        # Get messages
        cursor = self.messages_collection.find({"session_id": session_id}).sort("timestamp", 1)
        messages = []
        async for msg in cursor:
            msg["_id"] = str(msg["_id"])
            messages.append(msg)
        
        session["messages"] = messages
        return session
