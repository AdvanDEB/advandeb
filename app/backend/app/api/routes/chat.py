"""
Chat API routes.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from app.core.auth import get_current_user
from app.core.config import settings
from app.services.chat_service import ChatService


router = APIRouter()


@router.get("/default-model")
async def get_default_model(
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return info about the operator-configured default chat model.

    The frontend uses this to label the 'Nemotron (default)' picker option
    with the actual model name and provider. ``available`` is False when no
    default key is configured (the option should be hidden or disabled).
    """
    return {
        "available": bool(settings.DEFAULT_CHAT_API_KEY),
        "provider": settings.DEFAULT_CHAT_PROVIDER,
        "model": settings.DEFAULT_CHAT_MODEL,
        "rpm": settings.DEFAULT_CHAT_RPM,
    }


@router.get("/local-models")
async def list_local_models(
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """List locally-available Ollama models for the chat model picker.

    Queries Ollama's ``/api/tags`` directly so any authenticated user can pick a
    local model for their session (the curator-only KB endpoint is for admin UI).
    Returns an empty list (the UI then falls back to the server default) when
    Ollama is unreachable.
    """
    import httpx
    from advandeb_kb.config.settings import settings as kb_settings

    models: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [m["name"] for m in data.get("models", []) if m.get("name")]
    except Exception:
        models = []
    return {"models": models, "default_model": kb_settings.CHAT_ANSWER_MODEL}


class ChatMessage(BaseModel):
    """Chat message model."""
    role: str  # user, assistant, system
    content: str


class CitationResponse(BaseModel):
    """Canonical citation payload exposed to the frontend."""

    citation_id: str
    marker: str
    source_type: str
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    fact_id: Optional[str] = None
    stylized_fact_id: Optional[str] = None
    evidence_text: str = ""
    title: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    year: Optional[str | int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None


class ChatMessageResponse(ChatMessage):
    citations: List[CitationResponse] = Field(default_factory=list)
    evidence_mode: Optional[str] = None


class ChatRequest(BaseModel):
    """Chat request model."""
    messages: List[ChatMessage]
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response model."""
    message: ChatMessageResponse
    session_id: str
    suggested_questions: List[str] = Field(default_factory=list)


class RenameSessionRequest(BaseModel):
    """Rename session request."""
    title: str


class SessionLLMConfig(BaseModel):
    """Per-session BYOK LLM configuration.

    ``provider`` "ollama" (or no ``key_id``) means use the default local model.
    ``mode`` "react" always runs on Ollama regardless of provider.
    """
    provider: str = "ollama"
    mode: str = "final"
    model: Optional[str] = None
    key_id: Optional[str] = None


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


@router.get("/sessions/{session_id}/llm")
async def get_session_llm(
    session_id: str,
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get the per-session BYOK LLM config (defaults to local Ollama)."""
    chat_service = ChatService()
    config = await chat_service.get_session_llm_config(session_id, current_user["id"])
    return config or {"provider": "ollama", "mode": "final"}


@router.put("/sessions/{session_id}/llm")
async def set_session_llm(
    session_id: str,
    body: SessionLLMConfig,
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Set the per-session BYOK LLM config.

    A non-ollama provider requires a ``key_id`` the current user owns.
    """
    user_id = current_user["id"]

    if body.provider not in ("ollama", "default"):
        if not body.key_id:
            raise HTTPException(
                status_code=422,
                detail="key_id is required for non-ollama providers",
            )
        from app.services.llm_key_service import LLMKeyService
        owned = await LLMKeyService().list_keys(user_id)
        match = next((k for k in owned if k.id == body.key_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail="LLM key not found")
        if match.provider != body.provider:
            raise HTTPException(
                status_code=422,
                detail="key_id does not match the selected provider",
            )

    chat_service = ChatService()
    ok = await chat_service.set_session_llm_config(
        session_id, user_id, body.model_dump()
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return body.model_dump()


@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete a chat session and all its messages."""
    chat_service = ChatService()
    ok = await chat_service.delete_session(session_id, current_user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": session_id}


@router.put("/sessions/{session_id}/rename")
async def rename_chat_session_v2(
    session_id: str,
    body: RenameSessionRequest,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Rename a chat session (clean-path alias for the PUT /sessions/{id} route)."""
    chat_service = ChatService()
    ok = await chat_service.rename_session(session_id, current_user["id"], body.title)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"id": session_id, "title": body.title}


class SystemPromptRequest(BaseModel):
    system_prompt: str = ""


@router.put("/sessions/{session_id}/system-prompt")
async def set_session_system_prompt(
    session_id: str,
    body: SystemPromptRequest,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Store a custom system prompt for a session."""
    chat_service = ChatService()
    ok = await chat_service.set_session_system_prompt(
        session_id, current_user["id"], body.system_prompt
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "system_prompt": body.system_prompt}


class FeedbackRequest(BaseModel):
    rating: int = Field(..., ge=-1, le=1)


@router.post("/messages/{message_id}/feedback")
async def submit_message_feedback(
    message_id: str,
    body: FeedbackRequest,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Record thumbs-up / thumbs-down feedback for an assistant message."""
    db = ChatService().db
    await db.chat_message_feedback.update_one(
        {"message_id": message_id, "user_id": current_user["id"]},
        {
            "$set": {
                "rating": body.rating,
                "updated_at": datetime.now(timezone.utc),
            },
            "$setOnInsert": {
                "message_id": message_id,
                "user_id": current_user["id"],
                "created_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )
    return {"ok": True}
