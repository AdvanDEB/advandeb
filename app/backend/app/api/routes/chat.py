"""
Chat API routes.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

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
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response model."""
    message: ChatMessage
    session_id: str


class RenameSessionRequest(BaseModel):
    """Rename session request."""
    title: str


@router.post("/", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user)
):
    """Send a chat message and get AI response."""
    chat_service = ChatService()
    response = await chat_service.send_message(
        messages=[m.model_dump() for m in request.messages],
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
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.put("/sessions/{session_id}")
async def rename_chat_session(
    session_id: str,
    body: RenameSessionRequest,
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Rename a chat session."""
    chat_service = ChatService()
    ok = await chat_service.rename_session(session_id, current_user["id"], body.title)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"id": session_id, "title": body.title}
