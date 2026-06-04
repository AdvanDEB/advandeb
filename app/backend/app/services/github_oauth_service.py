"""
GitHub OAuth **device flow** → GitHub Models credential.

This is the only sanctioned OAuth flow the app exposes for LLM access. The
operator registers their *own* GitHub App (Device Flow enabled, ``Models: read``
permission) and sets ``GITHUB_OAUTH_CLIENT_ID``; no client secret is needed for
the device flow (it is a public client).

Flow:
    start()  → ask GitHub for a device/user code, stash the device code
               server-side, hand the user_code + verification_uri to the UI.
    poll()   → exchange the device code for an access token; on success fetch
               the GitHub login and persist an OAuth credential via
               LLMKeyService.create_oauth_connection().

The device code is a short-lived secret: it is encrypted at rest in the
``user_oauth_flows`` collection (TTL-expired) and never returned to the client.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.crypto import CryptoError, decrypt, encrypt
from app.core.database import get_database
from app.services.llm_key_service import LLMKeyService

logger = logging.getLogger(__name__)

DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
GRANT_DEVICE_CODE = "urn:ietf:params:oauth:grant-type:device_code"

# The GitHub Models credential is stored under the existing github_models provider
# so the chat path can reuse GitHubModelsProvider unchanged.
_PROVIDER = "github_models"

_HTTP_TIMEOUT = 15.0


def _client_id() -> str:
    cid = settings.GITHUB_OAUTH_CLIENT_ID
    if not cid:
        # Should be gated by the route, but fail loudly if reached.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured (GITHUB_OAUTH_CLIENT_ID unset).",
        )
    return cid


def _github_default_model() -> Optional[str]:
    """Default model to attach to a new GitHub Models connection."""
    try:
        from advandeb_kb.services.llm_providers import PROVIDERS

        cls = PROVIDERS.get(_PROVIDER)
        return getattr(cls, "default_model", None) if cls else None
    except Exception:  # noqa: BLE001 - never block the flow on this
        return None


class GitHubOAuthService:
    """Drives the GitHub device flow and persists the resulting credential."""

    def __init__(self) -> None:
        self.db = get_database()
        self.flows = self.db.user_oauth_flows
        self.keys = LLMKeyService()

    # -------------------------------------------------------------------- start

    async def start(self, user_id: str) -> Dict[str, Any]:
        """Begin a device flow. Returns the user-facing code + verification URI."""
        client_id = _client_id()
        payload: Dict[str, str] = {"client_id": client_id}
        # OAuth Apps use scopes; GitHub Apps ignore them (permissions are set on
        # the app). Only send a scope when the operator configured one.
        if settings.GITHUB_OAUTH_SCOPE:
            payload["scope"] = settings.GITHUB_OAUTH_SCOPE

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                DEVICE_CODE_URL, data=payload, headers={"Accept": "application/json"}
            )
        if resp.status_code != 200:
            logger.warning("github_oauth: device/code HTTP %s", resp.status_code)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub did not return a device code.",
            )
        data = resp.json()
        device_code = data.get("device_code")
        user_code = data.get("user_code")
        verification_uri = data.get("verification_uri")
        if not (device_code and user_code and verification_uri):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="GitHub device-code response was incomplete.",
            )

        flow_id = uuid.uuid4().hex
        interval = int(data.get("interval", 5))
        expires_in = int(data.get("expires_in", 900))
        await self.flows.insert_one(
            {
                "flow_id": flow_id,
                "user_id": user_id,
                "provider": _PROVIDER,
                "encrypted_device_code": encrypt(device_code),
                "interval": interval,
                # TTL index drives expiry; expires_at is informational.
                "created_at": datetime.now(timezone.utc),
            }
        )
        return {
            "flow_id": flow_id,
            "user_code": user_code,
            "verification_uri": verification_uri,
            "interval": interval,
            "expires_in": expires_in,
        }

    # --------------------------------------------------------------------- poll

    async def poll(self, user_id: str, flow_id: str) -> Dict[str, Any]:
        """Poll GitHub once for the pending flow.

        Returns one of:
            {"status": "pending"}
            {"status": "slow_down", "interval": int}
            {"status": "expired"}     (also when the flow row is gone)
            {"status": "denied"}
            {"status": "complete", "key": LLMKey}
        """
        flow = await self.flows.find_one({"flow_id": flow_id, "user_id": user_id})
        if not flow:
            return {"status": "expired"}

        try:
            device_code = decrypt(flow["encrypted_device_code"])
        except (CryptoError, KeyError):
            await self.flows.delete_one({"_id": flow["_id"]})
            return {"status": "expired"}

        client_id = _client_id()
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": GRANT_DEVICE_CODE,
                },
                headers={"Accept": "application/json"},
            )
            data = resp.json() if resp.content else {}

            access_token = data.get("access_token")
            if access_token:
                account_label = await self._fetch_login(client, access_token)
                key = await self.keys.create_oauth_connection(
                    user_id=user_id,
                    provider=_PROVIDER,
                    access_token=access_token,
                    refresh_token=data.get("refresh_token"),
                    expires_at=_expires_at(data.get("expires_in")),
                    account_label=account_label,
                    default_model=_github_default_model(),
                )
                await self.flows.delete_one({"_id": flow["_id"]})
                return {"status": "complete", "key": key}

        error = data.get("error")
        if error == "authorization_pending":
            return {"status": "pending"}
        if error == "slow_down":
            new_interval = int(data.get("interval", flow.get("interval", 5) + 5))
            await self.flows.update_one(
                {"_id": flow["_id"]}, {"$set": {"interval": new_interval}}
            )
            return {"status": "slow_down", "interval": new_interval}
        if error == "access_denied":
            await self.flows.delete_one({"_id": flow["_id"]})
            return {"status": "denied"}
        # expired_token / unsupported / anything else → treat as expired.
        await self.flows.delete_one({"_id": flow["_id"]})
        logger.info("github_oauth: poll ended for flow=%s error=%s", flow_id, error)
        return {"status": "expired"}

    @staticmethod
    async def _fetch_login(client: httpx.AsyncClient, access_token: str) -> Optional[str]:
        try:
            resp = await client.get(
                USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            if resp.status_code == 200:
                return resp.json().get("login")
        except Exception:  # noqa: BLE001 - login is display-only, never fatal
            logger.debug("github_oauth: /user lookup failed", exc_info=True)
        return None


def _expires_at(expires_in: Any) -> Optional[datetime]:
    """Convert GitHub's ``expires_in`` seconds into an absolute UTC instant."""
    try:
        secs = int(expires_in)
    except (TypeError, ValueError):
        return None
    if secs <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=secs)


async def refresh_github_token(refresh_token: str) -> Dict[str, Any]:
    """Exchange a refresh token for a new access token (GitHub App expiring tokens).

    Returns {access_token, refresh_token?, expires_at?}. Raises on transport error.
    """
    client_id = _client_id()
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
        )
        data = resp.json() if resp.content else {}
    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_at": _expires_at(data.get("expires_in")),
    }
