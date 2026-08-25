"""
Unit tests for UserService admin operations.

Focused on delete_user's cascade: an admin deleting an account must not leave
that user's encrypted provider keys or private chat history behind. Mongo is
mocked — no live database.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.user_service import UserService


class _FakeCursor:
    """Minimal async-iterable stand-in for a Motor cursor."""

    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        async def gen():
            for doc in self._docs:
                yield doc

        return gen()


def _collection(deleted_count: int = 0, docs=None) -> MagicMock:
    coll = MagicMock()
    coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=deleted_count))
    coll.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
    coll.find = MagicMock(return_value=_FakeCursor(docs or []))
    return coll


@pytest.fixture
def mock_db():
    db = MagicMock()
    # 24-hex so ObjectId() accepts it.
    db.users = _collection(deleted_count=1)
    db.chat_sessions = _collection(docs=[{"_id": "aaaaaaaaaaaaaaaaaaaaaaa1"}, {"_id": "aaaaaaaaaaaaaaaaaaaaaaa2"}])
    db.chat_messages = _collection()
    db.user_llm_keys = _collection()
    db.user_oauth_flows = _collection()
    db.chat_access_log = _collection()
    return db


USER_ID = "507f1f77bcf86cd799439011"


@pytest.mark.asyncio
async def test_delete_user_cascades_to_private_data(mock_db):
    with patch("app.services.user_service.get_database", return_value=mock_db):
        service = UserService()
        assert await service.delete_user(USER_ID) is True

    # Messages are keyed by session_id, so they must be removed by the ids
    # collected before the sessions were deleted.
    mock_db.chat_messages.delete_many.assert_awaited_once_with(
        {"session_id": {"$in": ["aaaaaaaaaaaaaaaaaaaaaaa1", "aaaaaaaaaaaaaaaaaaaaaaa2"]}}
    )
    mock_db.chat_sessions.delete_many.assert_awaited_once_with({"user_id": USER_ID})
    mock_db.user_llm_keys.delete_many.assert_awaited_once_with({"user_id": USER_ID})
    mock_db.user_oauth_flows.delete_many.assert_awaited_once_with({"user_id": USER_ID})
    mock_db.chat_access_log.delete_many.assert_awaited_once_with(
        {"target_user_id": USER_ID}
    )


@pytest.mark.asyncio
async def test_delete_user_missing_user_touches_nothing(mock_db):
    mock_db.users.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))

    with patch("app.services.user_service.get_database", return_value=mock_db):
        service = UserService()
        assert await service.delete_user(USER_ID) is False

    mock_db.chat_messages.delete_many.assert_not_awaited()
    mock_db.chat_sessions.delete_many.assert_not_awaited()
    mock_db.user_llm_keys.delete_many.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_user_with_no_sessions_skips_message_delete(mock_db):
    mock_db.chat_sessions.find = MagicMock(return_value=_FakeCursor([]))

    with patch("app.services.user_service.get_database", return_value=mock_db):
        service = UserService()
        assert await service.delete_user(USER_ID) is True

    mock_db.chat_messages.delete_many.assert_not_awaited()
    mock_db.user_llm_keys.delete_many.assert_awaited_once_with({"user_id": USER_ID})
