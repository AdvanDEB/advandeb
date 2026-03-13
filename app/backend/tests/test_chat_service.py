"""
Unit tests for ChatService.
MongoDB calls are patched so no live database is required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


@pytest.fixture
def mock_db():
    """Return a mock Motor database."""
    db = MagicMock()
    db.chat_sessions = MagicMock()
    db.chat_messages = MagicMock()
    return db


@pytest.fixture
def chat_service(mock_db):
    """ChatService with patched database and MCP client."""
    with patch("app.services.chat_service.get_database", return_value=mock_db):
        from app.services.chat_service import ChatService
        svc = ChatService()
    return svc, mock_db


# ── send_message ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_message_creates_session_when_none(chat_service):
    svc, db = chat_service

    inserted_id = MagicMock()
    inserted_id.__str__ = lambda s: "new-session-id"
    db.chat_sessions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=inserted_id))
    db.chat_messages.insert_one = AsyncMock()
    db.chat_sessions.update_one = AsyncMock()

    with patch.object(svc, "_get_mcp_response", new=AsyncMock(return_value={
        "role": "assistant", "content": "Hello"
    })):
        with patch("app.services.chat_service.settings") as mock_settings:
            mock_settings.MCP_SERVER_ENABLED = True
            result = await svc.send_message(
                messages=[{"role": "user", "content": "Hi"}],
                session_id="",
                user_id="user-1",
            )

    assert "session_id" in result
    assert result["message"]["role"] == "assistant"


@pytest.mark.asyncio
async def test_send_message_mcp_disabled_returns_placeholder(chat_service):
    svc, db = chat_service

    inserted_id = MagicMock()
    inserted_id.__str__ = lambda s: "sess-2"
    db.chat_sessions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=inserted_id))
    db.chat_messages.insert_one = AsyncMock()
    db.chat_sessions.update_one = AsyncMock()

    with patch("app.services.chat_service.settings") as mock_settings:
        mock_settings.MCP_SERVER_ENABLED = False
        result = await svc.send_message(
            messages=[{"role": "user", "content": "test"}],
            session_id="",
            user_id="u1",
        )

    assert "placeholder" in result["message"]["content"].lower()


# ── _touch_session ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_touch_session_updates_timestamp(chat_service):
    svc, db = chat_service
    db.chat_sessions.update_one = AsyncMock()

    await svc._touch_session("507f1f77bcf86cd799439011")

    db.chat_sessions.update_one.assert_awaited_once()
    call_args = db.chat_sessions.update_one.call_args
    assert "updated_at" in call_args[0][1]["$set"]


# ── list_sessions ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_sessions_returns_sorted_list(chat_service):
    svc, db = chat_service

    now = datetime.utcnow()
    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)

    async def async_iter(self):
        for item in [
            {"_id": MagicMock(__str__=lambda s: "s1"), "title": "A", "created_at": now, "updated_at": now},
            {"_id": MagicMock(__str__=lambda s: "s2"), "title": "B", "created_at": now, "updated_at": now},
        ]:
            yield item

    mock_cursor.__aiter__ = async_iter
    db.chat_sessions.find = MagicMock(return_value=mock_cursor)

    sessions = await svc.list_sessions("user-1")
    assert len(sessions) == 2
    assert sessions[0]["title"] == "A"
