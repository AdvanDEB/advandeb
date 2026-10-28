"""
WebSocket routes — real-time chat streaming.
"""
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query

from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue

from app.core.auth import resolve_user
from app.core.database import get_database
from app.services.chat_service import ChatService
from bson import ObjectId

router = APIRouter()


async def _get_ws_user(websocket: WebSocket, token: Optional[str]) -> Optional[dict]:
    """Resolve the JWT passed as ``?token=`` on the WebSocket upgrade.

    Goes through the shared :func:`resolve_user`, so a suspended account, a
    revoked session and an external contributor (who has no chat) are refused
    here exactly as on the REST routes. Returns None for any refusal; there is
    no anonymous fallback — an unauthenticated socket would spend the shared
    default-model key and its single global rate limit.
    """
    try:
        return await resolve_user(token, path=websocket.url.path)
    except HTTPException:
        return None


async def _check_generating(session_id: str, user_id: str, websocket: WebSocket) -> None:
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
        # Only the owner's own in-flight generations: the session id comes from
        # the URL, so without this any caller could probe another user's.
        if not await db.chat_sessions.find_one(
                {"_id": ObjectId(session_id), "user_id": user_id}, {"_id": 1}):
            return
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
    WebSocket URL. It is required: a missing, invalid or expired token, or an
    account that may not chat, gets close code 4401. The user_id is taken from
    the verified token, never from the JSON payload.

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
    user = await _get_ws_user(websocket, token)

    if user is None:
        # Accept then immediately close so the browser receives a readable
        # close frame (code 4401) rather than a raw HTTP 403.
        await websocket.accept()
        await websocket.close(code=4401, reason="Authentication required")
        return

    await websocket.accept()

    # user_id is authoritative from the verified JWT
    server_user_id = user["id"]
    active_session_id = session_id

    # Reconnect catch-up: surface any in-progress generations to the browser
    await _check_generating(active_session_id, server_user_id, websocket)

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
