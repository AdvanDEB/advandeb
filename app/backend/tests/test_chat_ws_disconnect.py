"""
F-031: leaving /chat while an answer was being generated lost the answer; the
conversation kept the question alone. The browser closes its socket on leaving
(ChatInterface unmount), and the turn was an async generator driven by the
socket loop: the next send failed, the generator was abandoned at its yield,
and the code after it — synthesis, storing the assistant message — never ran.

Here ws_chat is driven directly with a fake socket that goes away after the
first event, and a stand-in ChatService whose turn stores its answer only at
the end, the way ByokChatService.answer_stream does. No database, no network.
"""
import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from app.api.routes import ws


class _LeavingSocket:
    """Delivers one user message; the browser leaves after the first event."""

    def __init__(self):
        self.sent = []
        self._received = False

    async def accept(self):
        pass

    async def close(self, code=1000, reason=None):
        pass

    async def receive_text(self):
        if self._received:
            await asyncio.Event().wait()     # never another message
        self._received = True
        return json.dumps({"type": "user_message", "text": "What is kappa?"})

    async def send_text(self, text):
        if self.sent:
            raise WebSocketDisconnect(code=1001)
        self.sent.append(json.loads(text))


def _service(stored):
    class _SlowTurn:
        async def process_message_stream(self, **kwargs):
            yield {"type": "agent_activity", "agent": "chatbot", "status": "thinking"}
            await asyncio.sleep(0.05)                     # the model is still writing
            yield {"type": "agent_activity", "agent": "chatbot", "status": "working"}
            await asyncio.sleep(0.05)
            stored.append("answer")                       # stored at the very end
            yield {"type": "message", "role": "assistant", "content": "answer",
                   "session_id": "s1"}
    return _SlowTurn


@pytest.fixture
def signed_in(monkeypatch):
    async def user(*args, **kwargs):
        return {"id": "u1"}
    monkeypatch.setattr(ws, "_get_ws_user", user)


async def test_the_answer_is_stored_after_the_browser_left(monkeypatch, signed_in):
    stored = []
    monkeypatch.setattr(ws, "ChatService", _service(stored))
    sock = _LeavingSocket()

    await asyncio.wait_for(ws.ws_chat(sock, "new", ticket="t"), timeout=2)

    assert [e["status"] for e in sock.sent] == ["thinking"]   # it really left mid-turn
    assert stored == []                                        # not finished yet...
    for _ in range(40):
        if stored:
            break
        await asyncio.sleep(0.05)
    assert stored == ["answer"]                                # ...but it does finish
    await asyncio.sleep(0)
    assert not getattr(ws, "_detached_turns", set())           # and is let go


async def test_a_connected_browser_still_gets_every_event_in_order(monkeypatch, signed_in):
    stored = []
    monkeypatch.setattr(ws, "ChatService", _service(stored))

    class _StayingSocket(_LeavingSocket):
        async def send_text(self, text):
            self.sent.append(json.loads(text))
            if json.loads(text)["type"] == "message":
                raise WebSocketDisconnect(code=1000)   # end the test after the answer

    sock = _StayingSocket()
    await asyncio.wait_for(ws.ws_chat(sock, "new", ticket="t"), timeout=2)
    assert [e.get("status") or e["type"] for e in sock.sent] == ["thinking", "working", "message"]
    assert stored == ["answer"]


async def test_a_failing_turn_still_reports_its_error(monkeypatch, signed_in):
    class _Broken:
        async def process_message_stream(self, **kwargs):
            yield {"type": "agent_activity", "agent": "chatbot", "status": "thinking"}
            raise RuntimeError("upstream 503")

    monkeypatch.setattr(ws, "ChatService", _Broken)

    class _Socket(_LeavingSocket):
        async def send_text(self, text):
            self.sent.append(json.loads(text))

        async def receive_text(self):
            if self._received:
                raise WebSocketDisconnect(code=1000)
            return await super().receive_text()

    sock = _Socket()
    await asyncio.wait_for(ws.ws_chat(sock, "new", ticket="t"), timeout=2)
    assert sock.sent[-1] == {"type": "error", "detail": "upstream 503"}


# ── re-review of fd32fd0: bound, one turn per conversation, shutdown ──────── #

from bson import ObjectId  # noqa: E402


def _owned_session(app_db, user_id="u1"):
    sid = ObjectId()
    app_db.chat_sessions.docs.append({"_id": sid, "user_id": user_id, "title": "t"})
    return str(sid)


class _Script:
    """A socket that sends the given user messages, records what it gets, and
    disconnects when it has nothing more to say (after ``linger`` seconds)."""

    def __init__(self, texts, linger=0.0, leave_after_events=None):
        self.texts, self.linger, self.leave_after = list(texts), linger, leave_after_events
        self.sent = []

    async def accept(self):
        pass

    async def close(self, code=1000, reason=None):
        pass

    async def receive_text(self):
        if self.texts:
            return json.dumps({"type": "user_message", "text": self.texts.pop(0)})
        await asyncio.sleep(self.linger)
        raise WebSocketDisconnect(code=1000)

    async def send_text(self, text):
        if self.leave_after is not None and len(self.sent) >= self.leave_after:
            raise WebSocketDisconnect(code=1001)
        self.sent.append(json.loads(text))


def _hanging_service(calls):
    class _Hangs:
        async def process_message_stream(self, **kwargs):
            calls.append(kwargs["message"])
            yield {"type": "agent_activity", "agent": "chatbot", "status": "thinking"}
            yield {"type": "agent_activity", "agent": "retrieval", "status": "working"}
            await asyncio.sleep(30)                 # an agent that never answers
            yield {"type": "message", "content": "too late"}
    return _Hangs


async def test_a_turn_that_runs_too_long_is_stopped_and_says_so(monkeypatch, signed_in, fake_mongo, app_db):
    from app.core.config import settings
    monkeypatch.setattr(settings, "CHAT_TURN_TIMEOUT_SECONDS", 0.2)
    calls = []
    monkeypatch.setattr(ws, "ChatService", _hanging_service(calls))
    sid = _owned_session(app_db)

    sock = _Script(["slow question"])
    await asyncio.wait_for(ws.ws_chat(sock, sid, ticket="t"), timeout=3)

    assert sock.sent[0]["status"] == "thinking"
    assert sock.sent[-1]["type"] == "error"
    assert "was stopped" in sock.sent[-1]["detail"]
    stored = [m for m in app_db.chat_messages.docs if m["session_id"] == sid]
    assert [(m["role"], m["status"]) for m in stored] == [("assistant", "error")]
    assert "was stopped" in stored[0]["content"]


async def test_a_detached_turn_is_bounded_too(monkeypatch, signed_in, fake_mongo, app_db, caplog):
    from app.core.config import settings
    monkeypatch.setattr(settings, "CHAT_TURN_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(ws, "ChatService", _hanging_service([]))
    sid = _owned_session(app_db)

    sock = _Script(["slow question"], leave_after_events=1)     # gone by the 2nd event
    await asyncio.wait_for(ws.ws_chat(sock, sid, ticket="t"), timeout=3)
    assert ws._detached_turns
    with caplog.at_level("WARNING", logger="app.api.routes.ws"):
        await asyncio.wait_for(asyncio.gather(*ws._detached_turns), timeout=3)
    assert any("browser gone" in r.getMessage() for r in caplog.records)
    assert [m["status"] for m in app_db.chat_messages.docs if m["session_id"] == sid] == ["error"]


async def test_a_second_message_while_a_turn_runs_is_refused(monkeypatch, signed_in, fake_mongo, app_db):
    calls = []

    class _Slow:
        async def process_message_stream(self, **kwargs):
            calls.append(kwargs["message"])
            yield {"type": "agent_activity", "agent": "chatbot", "status": "thinking"}
            yield {"type": "agent_activity", "agent": "retrieval", "status": "working"}
            await asyncio.sleep(0.3)
            yield {"type": "message", "content": f"A to {kwargs['message']}", "session_id": kwargs["session_id"]}

    monkeypatch.setattr(ws, "ChatService", _Slow)
    sid = _owned_session(app_db)

    # Q1, then the browser leaves; the turn goes on without it.
    first = _Script(["Q1"], leave_after_events=1)
    await asyncio.wait_for(ws.ws_chat(first, sid, ticket="t"), timeout=3)
    # A new socket on the same conversation sends Q2 while A1 is still coming.
    second = _Script(["Q2"])
    await asyncio.wait_for(ws.ws_chat(second, sid, ticket="t"), timeout=3)

    assert calls == ["Q1"]                                     # no parallel turn
    assert second.sent == [{"type": "error", "detail": ws.BUSY_DETAIL}]

    await asyncio.wait_for(asyncio.gather(*ws._detached_turns), timeout=3)
    third = _Script(["Q2"])                                    # after A1: accepted
    await asyncio.wait_for(ws.ws_chat(third, sid, ticket="t"), timeout=3)
    assert calls == ["Q1", "Q2"]
    assert third.sent[-1]["content"] == "A to Q2"


async def test_shutdown_drains_then_cancels_detached_turns(caplog):
    finished = []

    async def quick():
        await asyncio.sleep(0.01)
        finished.append("quick")

    async def stuck():
        await asyncio.sleep(30)

    tasks = [asyncio.create_task(quick()), asyncio.create_task(stuck())]
    ws._detached_turns.update(tasks)
    for t in tasks:
        t.add_done_callback(ws._detached_turns.discard)
    with caplog.at_level("WARNING", logger="app.api.routes.ws"):
        await asyncio.wait_for(ws.drain_detached_turns(grace_seconds=0.2), timeout=2)
        await asyncio.sleep(0)
    assert finished == ["quick"]
    assert tasks[1].cancelled()
    assert any("1 detached chat turn(s) cancelled" in r.getMessage() for r in caplog.records)
