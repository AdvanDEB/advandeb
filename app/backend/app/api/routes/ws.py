"""
WebSocket routes — real-time chat streaming.
"""
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue

from app.core.auth import verify_token
from app.core.database import get_database
from app.services.chat_service import ChatService
from bson import ObjectId

router = APIRouter()


async def _get_ws_user(token: Optional[str]) -> Optional[dict]:
    """
    Validate a JWT passed as a query param on the WebSocket upgrade request.

    Returns a user dict on success, None if no token was provided (unauthenticated
    fallback — session stored as 'anonymous'), or closes with 4401 if the token is
    present but invalid.
    """
    if not token:
        return None
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        db = get_database()
        user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user_doc:
            return None
        return {
            "id": str(user_doc["_id"]),
            "email": user_doc.get("email", ""),
        }
    except Exception:
        return None


async def _check_generating(session_id: str, websocket: WebSocket) -> None:
    """
    On reconnect, check the app chat DB for any assistant messages that are still
    ``status="generating"`` (i.e. the ReAct loop started but the user's
    browser disconnected before it finished).

    Emits a ``{"type": "generating", "message_id": "..."}`` event for each
    such message so the frontend can show a spinner while waiting for the
    final ``{"type": "message"}`` event once the loop completes.
    """
    if not session_id or session_id == "new":
        return
    try:
        db = get_database()
        cursor = db.chat_messages.find(
            {"session_id": session_id, "status": "generating"},
            {"_id": 1},
        )
        async for doc in cursor:
            await websocket.send_text(json.dumps({
                "type": "generating",
                "message_id": str(doc["_id"]),
            }))
    except Exception:
        pass  # Don't block connection on best-effort check


@router.websocket("/chat/{session_id}")
async def ws_chat(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(default=None),
):
    """
    WebSocket endpoint for real-time agentic chat.

    Authentication: pass the JWT access token as ?token=<access_token> on the
    WebSocket URL. If a valid token is provided the server extracts the user_id
    from it and ignores any user_id in the JSON payload. If no token is provided
    the session is stored under 'anonymous'.

    Client sends:
      {"type": "user_message", "text": "..."}

    Server streams back (in order):
      {"type": "generating",    "message_id": "..."}            ← on reconnect only
      {"type": "agent_activity", "agent": "chatbot",      "status": "thinking",   "task": "<thought>"}
      {"type": "agent_activity", "agent": "<agent_name>", "status": "completed",  "task": "<tool>", "result": "..."}
      {"type": "message",        "role": "assistant",     "content": "...",
                                 "citations": [...], "suggested_questions": [...], "session_id": "..."}
      {"type": "error",          "detail": "..."}
    """
    # Validate token before accepting the connection
    user = await _get_ws_user(token)

    if token and user is None:
        # Accept then immediately close so the browser receives a readable
        # close frame (code 4401) rather than a raw HTTP 403.
        await websocket.accept()
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    await websocket.accept()

    # user_id is authoritative from the verified JWT; fall back to anonymous
    server_user_id = user["id"] if user else "anonymous"
    active_session_id = session_id

    # Reconnect catch-up: surface any in-progress generations to the browser
    await _check_generating(active_session_id, websocket)

    chat_service = ChatService()

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") != "user_message":
                continue

            text = data.get("text", "").strip()
            if not text:
                continue

            # Optional per-message LLM config (provider/model/key_id) — lets a
            # brand-new session use the chosen BYOK model on its first message.
            llm_config = data.get("llm_config")
            if not isinstance(llm_config, dict):
                llm_config = None

            # Stream all events back to the client as they arrive
            async for event in chat_service.process_message_stream(
                session_id=active_session_id,
                message=text,
                user_id=server_user_id,
                llm_config=llm_config,
            ):
                if event.get("type") == "message" and event.get("session_id"):
                    active_session_id = str(event["session_id"])
                    # Chatbot graph artifact depends on chat_sessions /
                    # chat_messages; refresh it once the turn lands.
                    graph_rebuild_queue.mark_dirty("chatbot")
                await websocket.send_text(json.dumps(event, default=str))

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "detail": str(exc)})
            )
        except Exception:
            pass
