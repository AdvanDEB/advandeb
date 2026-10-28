"""
WebSocket routes — real-time chat streaming.
"""
import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query

from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue

from app.core.auth import resolve_socket_user
from app.core.database import get_database
from app.services.chat_service import ChatService
from bson import ObjectId

router = APIRouter()
logger = logging.getLogger(__name__)

# A chat turn runs in its own task and the socket only relays its events. When
# the browser goes away mid-answer (the user left /chat, closed the tab, lost
# the network) the turn carries on and stores its answer; it used to be an
# async generator driven by the socket loop, abandoned at the next send, so the
# question was stored and the answer never was (F-031). Detached turns are
# held here until they finish so they are not garbage-collected mid-run.
_detached_turns: "set[asyncio.Task]" = set()
_TURN_DONE = object()


async def _run_turn(stream: AsyncIterator[Dict[str, Any]], sink: Dict[str, Any]) -> None:
    """Drive one turn to completion, handing its events to ``sink["queue"]``
    while someone is listening. An exception is handed over too."""
    try:
        async for event in stream:
            queue = sink["queue"]
            if queue is not None:
                queue.put_nowait(event)
    except Exception as exc:
        queue = sink["queue"]
        if queue is not None:
            queue.put_nowait(exc)
        else:
            logger.exception("chat turn failed after its socket closed")
    finally:
        queue = sink["queue"]
        if queue is not None:
            queue.put_nowait(_TURN_DONE)


async def _get_ws_user(
    websocket: WebSocket, ticket: Optional[str], token: Optional[str]
) -> Optional[dict]:
    """Resolve the credential on the WebSocket upgrade URL.

    A one-time ``?ticket=`` from POST /api/auth/ws-ticket (``?token=`` is the
    deprecated form). Goes through the shared resolver, so a suspended
    account, a revoked session and an external contributor (who has no chat)
    are refused here exactly as on the REST routes. Returns None for any
    refusal; there is no anonymous fallback — an unauthenticated socket would
    spend the shared default-model key and its single global rate limit.
    """
    try:
        return await resolve_socket_user(ticket, token, path=websocket.url.path)
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
    ticket: Optional[str] = Query(default=None),
    token: Optional[str] = Query(default=None),
):
    """
    WebSocket endpoint for real-time agentic chat.

    Authentication: pass a one-time ticket from POST /api/auth/ws-ticket as
    ?ticket=<ticket> on the WebSocket URL (?token=<access_token> is still
    accepted, deprecated). It is required: a missing, invalid, expired or used
    credential, or an account that may not chat, gets close code 4401. The
    user_id is taken from the verified credential, never from the JSON payload.

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
    user = await _get_ws_user(websocket, ticket, token)

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

            # The turn runs on its own (see _run_turn); relay its events.
            sink: Dict[str, Any] = {"queue": asyncio.Queue()}
            turn = asyncio.create_task(_run_turn(chat_service.process_message_stream(
                session_id=active_session_id,
                message=text,
                user_id=server_user_id,
                llm_config=llm_config,
            ), sink))
            try:
                while True:
                    event = await sink["queue"].get()
                    if event is _TURN_DONE:
                        break
                    if isinstance(event, Exception):
                        raise event
                    if event.get("type") == "message" and event.get("session_id"):
                        active_session_id = str(event["session_id"])
                        # Chatbot graph artifact depends on chat_sessions /
                        # chat_messages; refresh it once the turn lands.
                        graph_rebuild_queue.mark_dirty("chatbot")
                    await websocket.send_text(json.dumps(event, default=str))
            except BaseException:
                # The socket is gone (or this handler is being cancelled). Let
                # the turn finish without a listener, so its answer is stored.
                if not turn.done():
                    sink["queue"] = None
                    _detached_turns.add(turn)
                    turn.add_done_callback(_detached_turns.discard)
                raise

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "detail": str(exc)})
            )
        except Exception:
            pass
