"""
Chat API routes.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Dict, Any

from app.core.auth import get_current_user
from app.services.chat_service import ChatService


router = APIRouter()


class ChatMessage(BaseModel):
    """Chat message model."""
    role: str  # user, assistant, system
    content: str


class ChatRequest(BaseModel):
    """Chat request model."""
    messages: List[ChatMessage]
    session_id: str = None


class ChatResponse(BaseModel):
    """Chat response model."""
    message: ChatMessage
    session_id: str


@router.post("/", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user)
):
    """Send a chat message and get AI response."""
    chat_service = ChatService()
    response = await chat_service.send_message(
        messages=request.messages,
        session_id=request.session_id,
        user_id=current_user["id"]
    )
    return response


@router.get("/sessions")
async def list_chat_sessions(
    current_user: dict = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """List user's chat sessions."""
    chat_service = ChatService()
    sessions = await chat_service.list_sessions(current_user["id"])
    return sessions


@router.get("/sessions/{session_id}")
async def get_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get chat session by ID."""
    chat_service = ChatService()
    session = await chat_service.get_session(session_id, current_user["id"])
    return session
