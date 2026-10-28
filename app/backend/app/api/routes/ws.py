"""
WebSocket routes — real-time chat streaming.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query

from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue

from app.core.auth import resolve_socket_user
from app.core.config import settings
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
#
# Every turn is bounded by settings.CHAT_TURN_TIMEOUT_SECONDS: nobody may be
# waiting for a detached one, and an agent that keeps its socket alive with
# pings, or an SDK retrying for minutes, would otherwise hold the shared model
# key, a socket and memory indefinitely. One turn per conversation at a time:
# a second message while one is running is refused, so the stored history
# cannot interleave as Q1, Q2, A1, A2.
_detached_turns: "set[asyncio.Task]" = set()
_running: "dict[tuple[str, str], asyncio.Task]" = {}   # (user_id, session_id) -> turn
_TURN_DONE = object()

BUSY_DETAIL = ("An answer for this conversation is still being written. "
               "Wait for it to finish, then send your next message.")


def _timeout_detail() -> str:
    minutes = max(1, round(settings.CHAT_TURN_TIMEOUT_SECONDS / 60))
    return (f"The answer took longer than {minutes} minute{'s' if minutes != 1 else ''} "
            "and was stopped. Please ask again.")


def _claim(user_id: str, session_id: str, task: "asyncio.Task") -> None:
    """Record ``task`` as the running turn of this conversation until it ends."""
    if not session_id or session_id == "new":
        return
    key = (user_id, session_id)
    _running[key] = task

    def release(done: "asyncio.Task") -> None:
        if _running.get(key) is done:
            del _running[key]
    task.add_done_callback(release)


def _busy(user_id: str, session_id: str) -> bool:
    task = _running.get((user_id, session_id))
    return task is not None and not task.done()


async def _store_timeout_notice(user_id: str, session_id: str) -> None:
    """Leave the stopped turn's outcome in the conversation instead of nothing:
    an assistant message with status "error", as ByokChatService stores one."""
    if not session_id or session_id == "new":
        return
    try:
        db = get_database()
        if not await db.chat_sessions.find_one(
                {"_id": ObjectId(session_id), "user_id": user_id}, {"_id": 1}):
            return
        await db.chat_messages.insert_one({
            "session_id": session_id, "role": "assistant", "content": _timeout_detail(),
            "citations": [], "thoughts": [], "status": "error",
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception:
        logger.exception("could not store the timeout notice for session %s", session_id)


async def _run_turn(stream: AsyncIterator[Dict[str, Any]], sink: Dict[str, Any],
                    user_id: str = "", session_id: str = "new") -> None:
    """Drive one turn to completion (or to the time limit), handing its events
    to ``sink["queue"]`` while someone is listening. An exception is handed
    over too."""
    def hand_over(item: Any) -> bool:
        queue = sink["queue"]
        if queue is not None:
            queue.put_nowait(item)
        return queue is not None

    try:
        async with asyncio.timeout(settings.CHAT_TURN_TIMEOUT_SECONDS):
            async for event in stream:
                sid = event.get("session_id") if isinstance(event, dict) else None
                if sid and sid != session_id:
                    session_id = str(sid)
                    _claim(user_id, session_id, asyncio.current_task())
                hand_over(event)
    except TimeoutError:
        logger.warning("chat turn for session %s stopped after %ss (%s)", session_id,
                       settings.CHAT_TURN_TIMEOUT_SECONDS,
                       "browser connected" if sink["queue"] is not None else "browser gone")
        try:
            await stream.aclose()
        except Exception:
            pass
        await _store_timeout_notice(user_id, session_id)
        hand_over({"type": "error", "detail": _timeout_detail()})
    except Exception as exc:
        if not hand_over(exc):
            logger.exception("chat turn failed after its socket closed")
    finally:
        hand_over(_TURN_DONE)


async def drain_detached_turns(grace_seconds: float = 5.0) -> None:
    """At shutdown: give turns whose browser left a few seconds to store their
    answers, then cancel the rest, saying how many were lost."""
    pending = [t for t in _detached_turns if not t.done()]
    if not pending:
        return
    done, still = await asyncio.wait(pending, timeout=grace_seconds)
    for task in still:
        task.cancel()
    if still:
        logger.warning("shutdown: %d detached chat turn(s) cancelled unfinished, %d finished",
                       len(still), len(done))


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

            # One turn per conversation: refuse, do not run a second in parallel.
            if _busy(server_user_id, active_session_id):
                await websocket.send_text(json.dumps({"type": "error", "detail": BUSY_DETAIL}))
                continue

            # The turn runs on its own (see _run_turn); relay its events.
            sink: Dict[str, Any] = {"queue": asyncio.Queue()}
            turn = asyncio.create_task(_run_turn(chat_service.process_message_stream(
                session_id=active_session_id,
                message=text,
                user_id=server_user_id,
                llm_config=llm_config,
            ), sink, server_user_id, active_session_id))
            _claim(server_user_id, active_session_id, turn)
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
