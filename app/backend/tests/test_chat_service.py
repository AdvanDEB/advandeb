"""
Unit tests for ChatService.

The MongoDB layer is patched via ``app.services.chat_service.get_database`` so
no live MongoDB connection is required. The MCP gateway is patched via
``app.services.chat_service.MCPClient`` so no live WebSocket is opened.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Return a mock Motor-style async database with chat collections."""
    db = MagicMock()
    db.chat_sessions = MagicMock()
    db.chat_messages = MagicMock()
    return db


@pytest.fixture
def chat_service(mock_db):
    """ChatService instance built against a mocked database."""
    with patch(
        "app.services.chat_service.get_database",
        return_value=mock_db,
    ):
        from app.services.chat_service import ChatService

        svc = ChatService()
    return svc, mock_db


# ---------------------------------------------------------------------------
# send_message — MCP disabled branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_mcp_disabled_returns_message(chat_service):
    """When MCP is disabled, send_message returns a friendly notice."""
    svc, _db = chat_service

    with patch("app.services.chat_service.settings") as mock_settings:
        mock_settings.MCP_SERVER_ENABLED = False
        # Ensure neither the default-key nor BYOK path is taken so the test
        # reaches the MCP-disabled guard.
        mock_settings.DEFAULT_CHAT_API_KEY = None
        response = await svc.send_message(
            [{"role": "user", "content": "hi"}],
            session_id="",
            user_id="u1",
        )

    # Shape: {"message": {...}, "session_id": ...}
    assert "message" in response
    assert "session_id" in response
    assert isinstance(response["message"], dict)
    assert response["message"]["role"] == "assistant"
    assert "not enabled" in response["message"]["content"].lower()


# ---------------------------------------------------------------------------
# send_message — MCP enabled, success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_calls_mcp_when_enabled(chat_service):
    """When MCP is enabled, send_message delegates to MCPClient.call_tool."""
    svc, _db = chat_service

    with patch("app.services.chat_service.settings") as mock_settings, patch(
        "app.services.chat_service.MCPClient"
    ) as MockMCPClient:
        mock_settings.MCP_SERVER_ENABLED = True
        mock_settings.DEFAULT_CHAT_API_KEY = None

        mock_instance = MockMCPClient.return_value
        mock_instance.call_tool = AsyncMock(
            return_value={
                "answer": "ok",
                "citations": [],
                "session_id": "s1",
            }
        )

        response = await svc.send_message(
            [{"role": "user", "content": "hi"}],
            session_id="",
            user_id="u1",
        )

    mock_instance.call_tool.assert_awaited_once()
    assert response["message"]["role"] == "assistant"
    assert response["message"]["content"] == "ok"
    assert response["message"]["citations"] == []
    assert response["session_id"] == "s1"


# ---------------------------------------------------------------------------
# send_message — MCP enabled, failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_mcp_failure_returns_error_message(chat_service):
    """If MCPClient.call_tool raises, send_message returns an Error: message."""
    svc, _db = chat_service

    with patch("app.services.chat_service.settings") as mock_settings, patch(
        "app.services.chat_service.MCPClient"
    ) as MockMCPClient:
        mock_settings.MCP_SERVER_ENABLED = True
        mock_settings.DEFAULT_CHAT_API_KEY = None

        mock_instance = MockMCPClient.return_value
        mock_instance.call_tool = AsyncMock(side_effect=RuntimeError("boom"))

        response = await svc.send_message(
            [{"role": "user", "content": "hi"}],
            session_id="",
            user_id="u1",
        )

    assert response["message"]["role"] == "assistant"
    assert response["message"]["content"].startswith("Error:")
    assert "boom" in response["message"]["content"]


# ---------------------------------------------------------------------------
# list_sessions — sort order preserved from cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sessions_sorted_descending(chat_service):
    """Sessions are returned in the order produced by the (mocked) cursor."""
    svc, db = chat_service

    now = datetime.now(timezone.utc)

    # _id objects whose str() is deterministic
    id_newer = MagicMock()
    id_newer.__str__ = lambda self: "sess-newer"
    id_older = MagicMock()
    id_older.__str__ = lambda self: "sess-older"

    session_docs = [
        {
            "_id": id_newer,
            "title": "Newer",
            "created_at": now,
            "updated_at": now,
        },
        {
            "_id": id_older,
            "title": "Older",
            "created_at": now,
            "updated_at": now,
        },
    ]

    async def _aiter(self):
        for doc in session_docs:
            yield doc

    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.__aiter__ = _aiter

    db.chat_sessions.find = MagicMock(return_value=mock_cursor)

    sessions = await svc.list_sessions("user-1")

    assert len(sessions) == 2
    assert sessions[0]["id"] == "sess-newer"
    assert sessions[0]["title"] == "Newer"
    assert sessions[1]["id"] == "sess-older"
    assert sessions[1]["title"] == "Older"

    # Verify sort was called descending on updated_at
    mock_cursor.sort.assert_called_once_with("updated_at", -1)


# ---------------------------------------------------------------------------
# get_session — invalid ObjectId returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_returns_none_for_invalid_objectid(chat_service):
    """A malformed session_id must short-circuit to None (no DB call)."""
    svc, db = chat_service

    db.chat_sessions.find_one = AsyncMock()

    result = await svc.get_session("not-an-objectid", "user-1")

    assert result is None
    db.chat_sessions.find_one.assert_not_awaited()


# ---------------------------------------------------------------------------
# rename_session — invalid ObjectId returns False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_session_returns_false_for_invalid_objectid(chat_service):
    """A malformed session_id must short-circuit rename to False."""
    svc, db = chat_service

    db.chat_sessions.update_one = AsyncMock()

    result = await svc.rename_session(
        "not-an-objectid", "user-1", "New Title"
    )

    assert result is False
    db.chat_sessions.update_one.assert_not_awaited()
