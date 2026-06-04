"""
Unit tests for the sanctioned GitHub device-flow BYOK path.

Covers:
  * GitHubOAuthService.start / poll (device flow), with httpx + Mongo mocked.
  * LLMKeyService.get_credential OAuth branch, including refresh-on-expiry.

No live HTTP or MongoDB is used. Real Fernet crypto runs against a throwaway
key injected into settings, so encrypt/decrypt round-trips are exercised.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.core import config


@pytest.fixture
def crypto_key():
    """Inject a valid Fernet key into settings for the duration of a test."""
    key = Fernet.generate_key().decode()
    with patch.object(config.settings, "LLM_KEY_ENCRYPTION_KEY", key):
        yield key


@pytest.fixture
def github_client_id():
    with patch.object(config.settings, "GITHUB_OAUTH_CLIENT_ID", "test-client"), patch.object(
        config.settings, "GITHUB_OAUTH_SCOPE", None
    ):
        yield "test-client"


# ---------------------------------------------------------------------------
# Fake httpx client
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, payload: dict | None = None, status_code: int = 200):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = b"{}" if payload is not None else b""

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Async-context-manager stand-in for httpx.AsyncClient."""

    def __init__(self, routes: dict):
        # routes: {("POST"|"GET", url): _FakeResp}
        self._routes = routes
        self.calls: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, headers=None):
        self.calls.append(("POST", url, data))
        return self._routes[("POST", url)]

    async def get(self, url, headers=None):
        self.calls.append(("GET", url, None))
        return self._routes[("GET", url)]


def _make_service(mock_db):
    from app.services.github_oauth_service import GitHubOAuthService

    with patch(
        "app.services.github_oauth_service.get_database", return_value=mock_db
    ), patch("app.services.github_oauth_service.LLMKeyService"):
        svc = GitHubOAuthService()
    return svc


def _flows_collection():
    flows = MagicMock()
    flows.insert_one = AsyncMock()
    flows.find_one = AsyncMock()
    flows.delete_one = AsyncMock()
    flows.update_one = AsyncMock()
    return flows


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_user_code_and_stores_flow(crypto_key, github_client_id):
    from app.services import github_oauth_service as mod

    db = MagicMock()
    db.user_oauth_flows = _flows_collection()
    svc = _make_service(db)
    svc.flows = db.user_oauth_flows

    fake = _FakeClient(
        {
            ("POST", mod.DEVICE_CODE_URL): _FakeResp(
                {
                    "device_code": "dev-code-123",
                    "user_code": "WXYZ-1234",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 5,
                    "expires_in": 900,
                }
            )
        }
    )
    with patch.object(mod.httpx, "AsyncClient", return_value=fake):
        out = await svc.start("user-1")

    assert out["user_code"] == "WXYZ-1234"
    assert out["verification_uri"].endswith("/login/device")
    assert out["flow_id"]
    # A pending flow was persisted, and the device code is NOT returned to the client.
    svc.flows.insert_one.assert_awaited_once()
    stored = svc.flows.insert_one.await_args.args[0]
    assert "device_code" not in out
    assert stored["encrypted_device_code"] != "dev-code-123"  # encrypted at rest


# ---------------------------------------------------------------------------
# poll()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_pending(crypto_key, github_client_id):
    from app.core.crypto import encrypt
    from app.services import github_oauth_service as mod

    db = MagicMock()
    db.user_oauth_flows = _flows_collection()
    db.user_oauth_flows.find_one = AsyncMock(
        return_value={
            "_id": "f1",
            "flow_id": "flow-1",
            "user_id": "user-1",
            "encrypted_device_code": encrypt("dev-code-123"),
            "interval": 5,
        }
    )
    svc = _make_service(db)
    svc.flows = db.user_oauth_flows

    fake = _FakeClient(
        {("POST", mod.TOKEN_URL): _FakeResp({"error": "authorization_pending"})}
    )
    with patch.object(mod.httpx, "AsyncClient", return_value=fake):
        out = await svc.poll("user-1", "flow-1")

    assert out == {"status": "pending"}
    svc.flows.delete_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_complete_stores_connection(crypto_key, github_client_id):
    from app.core.crypto import encrypt
    from app.services import github_oauth_service as mod

    db = MagicMock()
    db.user_oauth_flows = _flows_collection()
    db.user_oauth_flows.find_one = AsyncMock(
        return_value={
            "_id": "f1",
            "flow_id": "flow-1",
            "user_id": "user-1",
            "encrypted_device_code": encrypt("dev-code-123"),
            "interval": 5,
        }
    )
    svc = _make_service(db)
    svc.flows = db.user_oauth_flows
    # Stub the credential store so we don't touch the provider/registry here.
    svc.keys = MagicMock()
    svc.keys.create_oauth_connection = AsyncMock(return_value={"id": "k1", "account_label": "octocat"})

    fake = _FakeClient(
        {
            ("POST", mod.TOKEN_URL): _FakeResp(
                {"access_token": "gho_abc", "refresh_token": "ghr_def", "expires_in": 28800}
            ),
            ("GET", mod.USER_URL): _FakeResp({"login": "octocat"}),
        }
    )
    with patch.object(mod.httpx, "AsyncClient", return_value=fake):
        out = await svc.poll("user-1", "flow-1")

    assert out["status"] == "complete"
    svc.keys.create_oauth_connection.assert_awaited_once()
    kwargs = svc.keys.create_oauth_connection.await_args.kwargs
    assert kwargs["access_token"] == "gho_abc"
    assert kwargs["refresh_token"] == "ghr_def"
    assert kwargs["account_label"] == "octocat"
    assert kwargs["expires_at"] is not None
    svc.flows.delete_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_poll_unknown_flow_is_expired(crypto_key, github_client_id):
    db = MagicMock()
    db.user_oauth_flows = _flows_collection()
    db.user_oauth_flows.find_one = AsyncMock(return_value=None)
    svc = _make_service(db)
    svc.flows = db.user_oauth_flows

    out = await svc.poll("user-1", "missing")
    assert out == {"status": "expired"}


# ---------------------------------------------------------------------------
# LLMKeyService.get_credential — OAuth branch
# ---------------------------------------------------------------------------


def _key_service(mock_collection):
    from app.services.llm_key_service import LLMKeyService

    db = MagicMock()
    db.user_llm_keys = mock_collection
    with patch("app.services.llm_key_service.get_database", return_value=db):
        return LLMKeyService()


@pytest.mark.asyncio
async def test_get_credential_oauth_non_expiring_returns_token(crypto_key):
    from bson import ObjectId

    from app.core.crypto import encrypt

    oid = ObjectId()
    coll = MagicMock()
    coll.find_one = AsyncMock(
        return_value={
            "_id": oid,
            "user_id": "u1",
            "provider": "github_models",
            "credential_type": "oauth",
            "encrypted_access_token": encrypt("gho_live"),
            "encrypted_refresh_token": None,
            "access_token_expires_at": None,
        }
    )
    coll.update_one = AsyncMock()
    svc = _key_service(coll)

    token = await svc.get_credential("u1", str(oid))
    assert token == "gho_live"


@pytest.mark.asyncio
async def test_get_credential_oauth_refreshes_when_expired(crypto_key):
    from bson import ObjectId

    from app.core.crypto import encrypt

    oid = ObjectId()
    coll = MagicMock()
    coll.find_one = AsyncMock(
        return_value={
            "_id": oid,
            "user_id": "u1",
            "provider": "github_models",
            "credential_type": "oauth",
            "encrypted_access_token": encrypt("gho_old"),
            "encrypted_refresh_token": encrypt("ghr_refresh"),
            "access_token_expires_at": datetime.now(timezone.utc) - timedelta(minutes=5),
        }
    )
    coll.update_one = AsyncMock()
    svc = _key_service(coll)

    fresh = {
        "access_token": "gho_new",
        "refresh_token": "ghr_new",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=8),
    }
    with patch(
        "app.services.github_oauth_service.refresh_github_token",
        new=AsyncMock(return_value=fresh),
    ):
        token = await svc.get_credential("u1", str(oid))

    assert token == "gho_new"
    # The refreshed token was persisted back.
    assert coll.update_one.await_count >= 1
