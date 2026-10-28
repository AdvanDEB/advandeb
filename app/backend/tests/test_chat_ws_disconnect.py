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
