"""
Unit tests for authorization, security guards, and input sanitization.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException

from app.core.dependencies import require_role
from app.models.model import ModelCreate
from app.services.model_service import ModelService
from app.services.user_service import UserService


# ---------------------------------------------------------------------------
# require_role dependency factory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_require_role_factory_returns_callable():
    """require_role must be a synchronous factory returning an async role checker."""
    checker = require_role(["administrator", "knowledge_curator"])
    assert callable(checker)

    # Valid role passes
    user_admin = {"id": "u1", "roles": ["administrator"]}
    res = await checker(current_user=user_admin)
    assert res == user_admin

    # Invalid role raises HTTP 403
    user_explorator = {"id": "u2", "roles": ["knowledge_explorator"]}
    with pytest.raises(HTTPException) as exc_info:
        await checker(current_user=user_explorator)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# ModelService ownership & authorization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_model_update_and_delete_ownership():
    mock_db = MagicMock()
    mock_coll = MagicMock()
    mock_db.models = mock_coll

    with patch("app.services.model_service.get_database", return_value=mock_db):
        service = ModelService()

        # Malformed ID returns None/False
        assert await service.get_model("invalid-id") is None
        assert await service.update_model("invalid-id", ModelCreate(name="m", description="d", model_type="t", scenario_id="s1"), "u1") is None
        assert await service.delete_model("invalid-id", "u1") is False

        # Model owned by user-1
        oid = ObjectId()
        mock_coll.find_one = AsyncMock(return_value={
            "_id": oid,
            "name": "Model 1",
            "description": "Desc",
            "model_type": "type",
            "creator_id": "user-1",
            "status": "draft",
            "version": 1,
            "provenance": [],
            "created_at": None,
            "updated_at": None,
        })
        mock_coll.update_one = AsyncMock()
        mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        # Different non-admin user cannot modify -> 403
        with pytest.raises(HTTPException) as exc_info:
            await service.update_model(str(oid), ModelCreate(name="New", description="d", model_type="t", scenario_id="s1"), user_id="user-2", is_admin=False)
        assert exc_info.value.status_code == 403

        # Different non-admin user cannot delete -> 403
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_model(str(oid), user_id="user-2", is_admin=False)
        assert exc_info.value.status_code == 403

        # Admin CAN delete even if not owner
        deleted = await service.delete_model(str(oid), user_id="admin-user", is_admin=True)
        assert deleted is True


# ---------------------------------------------------------------------------
# UserService regex sanitization
# ---------------------------------------------------------------------------

def test_user_service_build_filter_escapes_regex():
    """Special regex chars in search query must be escaped."""
    filt = UserService._build_filter(q="user+test(1)@example.com.*")
    regex_val = filt["$or"][0]["email"]["$regex"]
    assert regex_val == r"user\+test\(1\)@example\.com\.\*"
