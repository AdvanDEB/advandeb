"""
LLMKeyService — encrypted per-user BYOK key storage + CRUD.

Storage layout (collection ``user_llm_keys`` in the app MongoDB):
    {
        _id:            ObjectId,
        user_id:        str   (str(ObjectId) of the owning user),
        provider:       str   ("anthropic" | "openai" | "gemini" | "github_models"
                               | "nvidia"),
        credential_type:str   ("api_key" | "oauth"),
        label:          str | None,
        default_model:  str | None,
        # api_key rows:
        encrypted_key:  str   (Fernet ciphertext of the plaintext api key),
        key_last_4:     str   (last 4 chars of the plaintext, for UI display),
        # oauth rows (e.g. "Connect with GitHub" → GitHub Models):
        encrypted_access_token:  str   (Fernet ciphertext of the access token),
        encrypted_refresh_token: str | None,
        access_token_expires_at: datetime | None,
        account_label:           str | None  (e.g. the GitHub login),
        created_at:     datetime (UTC),
        last_used_at:   datetime | None,
    }

The plaintext secret (api key or OAuth token) is NEVER persisted in the clear,
logged, or returned by any public method except ``get_credential`` — which is
reserved for internal callers (e.g. the chat pipeline) that need to mint an
outbound request.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

from app.core.crypto import CryptoError, decrypt, encrypt
from app.core.database import get_database
from app.models.llm_key import LLMKey

# Provider abstraction lives in the KB package (built by another agent).
# Imported lazily inside methods so this module is importable even if the
# providers package is not yet installed in a given environment.

logger = logging.getLogger(__name__)


# Provider names exposed via BYOK. Ollama is intentionally excluded —
# it is a local provider with no key to store.
#
# This is the SINGLE source of truth: the /providers route filters its catalog
# through this same set, so what the UI offers and what create_key() accepts
# cannot drift apart. (They did once: the picker offered "nvidia" while this
# allow-list omitted it, so every NVIDIA key was rejected with a 422.)
BYOK_PROVIDER_NAMES = {"anthropic", "openai", "gemini", "github_models", "nvidia"}

#: Backwards-compatible private alias.
_BYOK_PROVIDER_NAMES = BYOK_PROVIDER_NAMES


def _pick_default_model(
    provider_instance, models: List[str], preferred: Optional[str]
) -> Optional[str]:
    """Choose a sensible default model from a live catalog.

    Preference order: an explicitly ``preferred`` model that's offered → the
    provider's curated default if offered → the first catalog entry → whatever
    we were given (so an empty catalog still yields *something*).
    """
    if preferred and preferred in models:
        return preferred
    curated = getattr(provider_instance, "default_model", "") or None
    if curated and curated in models:
        return curated
    if models:
        return models[0]
    return preferred or curated


def _doc_to_model(doc: dict) -> LLMKey:
    """Convert a stored Mongo document to the outbound ``LLMKey`` model."""
    return LLMKey(
        id=str(doc["_id"]),
        provider=doc["provider"],
        credential_type=doc.get("credential_type", "api_key"),
        label=doc.get("label"),
        default_model=doc.get("default_model"),
        key_last_4=doc.get("key_last_4"),
        account_label=doc.get("account_label"),
        created_at=doc["created_at"],
        last_used_at=doc.get("last_used_at"),
    )


class LLMKeyService:
    """Business logic for the BYOK key store."""

    def __init__(self):
        self.db = get_database()
        self.collection = self.db.user_llm_keys

    # ------------------------------------------------------------------ create

    async def create_key(
        self,
        user_id: str,
        provider: str,
        api_key: str,
        label: Optional[str] = None,
        default_model: Optional[str] = None,
    ) -> LLMKey:
        """Validate, encrypt, and persist a new BYOK key for ``user_id``.

        Raises:
            HTTPException 422 — unknown provider name.
            HTTPException 400 — provider validate() rejected the key.
            HTTPException 409 — duplicate (user_id, provider, label).
            HTTPException 500 — encryption misconfigured.
        """
        # 1. Validate the provider name. We deliberately use a hard allow-list
        #    of BYOK-eligible providers so that "ollama" can't sneak in.
        if provider not in _BYOK_PROVIDER_NAMES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown provider: {provider!r}",
            )

        from advandeb_kb.services.llm_providers import PROVIDERS, get_provider
        from advandeb_kb.services.llm_providers.base import ProviderAuthError, ProviderError

        if provider not in PROVIDERS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown provider: {provider!r}",
            )

        # 2. Round-trip the key through the provider so we never store junk.
        #    validate() is the authoritative check — do NOT assume list_models()
        #    implies it. NVIDIA NIM serves GET /v1/models with no Authorization
        #    header at all, so for that provider a catalog fetch succeeds for any
        #    string and junk keys were being stored, failing only later at chat
        #    time. Each provider's validate() knows what actually authenticates.
        try:
            provider_instance = get_provider(provider, api_key=api_key)
            await provider_instance.validate()
            models = await provider_instance.list_models()
        except ProviderAuthError as exc:
            # Sanitised message — never include the plaintext key.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"API key failed validation: {exc.message}",
            ) from None
        except ProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"API key failed validation: {exc.message}",
            ) from None
        except Exception as exc:  # noqa: BLE001
            # Final safety net — drop the exception details that may have
            # captured the api_key (e.g. via a request URL). Use only the
            # exception class name.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"API key failed validation: {type(exc).__name__}",
            ) from None

        # The model is chosen automatically: the provider's curated default if
        # the key can use it, otherwise the first model the catalog offers.
        default_model = _pick_default_model(provider_instance, models, default_model)

        # 3. Encrypt + compute the last-4 fingerprint.
        try:
            encrypted_key = encrypt(api_key)
        except CryptoError as exc:
            # Surface as a 500 — operator misconfiguration.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from None

        key_last_4 = api_key[-4:]

        # 4. Duplicate check on (user_id, provider, label) — matches the
        #    unique index in ensure_app_indexes().
        existing = await self.collection.find_one(
            {"user_id": user_id, "provider": provider, "label": label}
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A key for this (provider, label) already exists",
            )

        # 5. Insert.
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": user_id,
            "provider": provider,
            "credential_type": "api_key",
            "label": label,
            "default_model": default_model,
            "encrypted_key": encrypted_key,
            "key_last_4": key_last_4,
            "created_at": now,
            "last_used_at": None,
        }
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        logger.info(
            "llm_key_service: created key user=%s provider=%s label=%s last4=%s",
            user_id, provider, label, key_last_4,
        )
        return _doc_to_model(doc)

    # ------------------------------------------------------- list (models)

    async def list_models_for_key(self, user_id: str, key_id: str) -> dict:
        """Fetch the live model catalog for a *stored* key the user owns.

        Drives the chat model picker: the plaintext secret never leaves the
        server, so the UI asks by ``key_id`` and we decrypt/refresh internally.

        Returns ``{"models": [...], "default_model": str}``.

        Raises:
            HTTPException 404 — key missing / malformed / undecryptable.
            HTTPException 400 — provider rejected the credential (sanitised).
        """
        try:
            oid = ObjectId(key_id)
        except (InvalidId, TypeError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
            ) from None
        doc = await self.collection.find_one({"_id": oid, "user_id": user_id})
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
            )

        if doc.get("credential_type") == "oauth":
            secret = await self._fresh_oauth_token(doc)
            if not secret:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="OAuth token could not be refreshed or decrypted",
                )
        else:
            try:
                secret = decrypt(doc["encrypted_key"])
            except CryptoError:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
                ) from None

        from advandeb_kb.services.llm_providers import get_provider
        from advandeb_kb.services.llm_providers.base import ProviderAuthError, ProviderError

        try:
            provider_instance = get_provider(doc["provider"], api_key=secret)
            models = await provider_instance.list_models()
        except ProviderAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"API key failed validation: {exc.message}",
            ) from None
        except ProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not list models: {exc.message}",
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not list models: {type(exc).__name__}",
            ) from None

        default = _pick_default_model(provider_instance, models, doc.get("default_model"))
        return {"models": models, "default_model": default}

    # ------------------------------------------------------ create (oauth)

    async def create_oauth_connection(
        self,
        user_id: str,
        provider: str,
        access_token: str,
        *,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        account_label: Optional[str] = None,
        default_model: Optional[str] = None,
        label: Optional[str] = None,
    ) -> LLMKey:
        """Validate, encrypt, and persist an OAuth-obtained credential.

        Used by the device-flow services (e.g. GitHub Models). The access token
        is round-tripped through the provider's ``validate()`` so we never store
        a dead token, then encrypted at rest exactly like a pasted api key.

        ``label`` defaults to ``account_label`` so an OAuth row never collides
        with a pasted-key row (which is typically unlabeled) on the
        (user_id, provider, label) unique index, and so reconnecting the same
        account updates rather than duplicates.

        Raises:
            HTTPException 422 — unknown provider name.
            HTTPException 400 — provider validate() rejected the token.
            HTTPException 500 — encryption misconfigured.
        """
        if provider not in _BYOK_PROVIDER_NAMES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown provider: {provider!r}",
            )

        from advandeb_kb.services.llm_providers import get_provider
        from advandeb_kb.services.llm_providers.base import ProviderAuthError, ProviderError

        # Validate the token works before we persist it.
        try:
            provider_instance = get_provider(provider, api_key=access_token)
            ok = await provider_instance.validate()
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="OAuth token failed validation",
                )
        except HTTPException:
            raise
        except (ProviderAuthError, ProviderError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OAuth token failed validation: {exc.message}",
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OAuth token failed validation: {type(exc).__name__}",
            ) from None

        try:
            encrypted_access = encrypt(access_token)
            encrypted_refresh = encrypt(refresh_token) if refresh_token else None
        except CryptoError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from None

        effective_label = label or account_label
        now = datetime.now(timezone.utc)
        set_fields = {
            "user_id": user_id,
            "provider": provider,
            "credential_type": "oauth",
            "label": effective_label,
            "default_model": default_model,
            "encrypted_access_token": encrypted_access,
            "encrypted_refresh_token": encrypted_refresh,
            "access_token_expires_at": expires_at,
            "account_label": account_label,
            "last_used_at": None,
        }
        # Upsert on (user_id, provider, label): reconnecting the same account
        # refreshes the stored tokens in place rather than hitting the unique index.
        await self.collection.update_one(
            {"user_id": user_id, "provider": provider, "label": effective_label},
            {"$set": set_fields, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        stored = await self.collection.find_one(
            {"user_id": user_id, "provider": provider, "label": effective_label}
        )
        logger.info(
            "llm_key_service: stored oauth connection user=%s provider=%s account=%s",
            user_id, provider, account_label,
        )
        return _doc_to_model(stored)

    # -------------------------------------------------------------------- list

    async def list_keys(self, user_id: str) -> List[LLMKey]:
        """Return all stored keys for ``user_id`` (no plaintext)."""
        cursor = self.collection.find({"user_id": user_id}).sort("created_at", -1)
        return [_doc_to_model(doc) async for doc in cursor]

    # ------------------------------------------------------------------ delete

    async def delete_key(self, user_id: str, key_id: str) -> bool:
        """Delete the given key if it exists and is owned by ``user_id``.

        Returns True on deletion, False if the id is malformed or no matching
        document was found. Never raises 500 on a malformed key_id.
        """
        try:
            oid = ObjectId(key_id)
        except (InvalidId, TypeError):
            return False
        result = await self.collection.delete_one({"_id": oid, "user_id": user_id})
        return result.deleted_count == 1

    # ------------------------------------------------------- get (decrypted)

    async def get_decrypted_key(self, user_id: str, key_id: str) -> Optional[str]:
        """Return the plaintext api key, or None if missing / malformed.

        Reserved for internal callers (chat pipeline) that need the secret to
        mint an outbound provider request. Updates ``last_used_at``.

        Never exposed by an HTTP route — the plaintext is end-of-life data.
        """
        try:
            oid = ObjectId(key_id)
        except (InvalidId, TypeError):
            return None
        doc = await self.collection.find_one({"_id": oid, "user_id": user_id})
        if not doc:
            return None
        try:
            plaintext = decrypt(doc["encrypted_key"])
        except CryptoError:
            logger.warning(
                "llm_key_service: failed to decrypt key id=%s user=%s",
                key_id, user_id,
            )
            return None
        await self.collection.update_one(
            {"_id": oid}, {"$set": {"last_used_at": datetime.now(timezone.utc)}}
        )
        return plaintext

    # ------------------------------------------------ get (any credential)

    async def get_credential(self, user_id: str, key_id: str) -> Optional[str]:
        """Return the usable secret for ``key_id``, or None if missing / malformed.

        Generalises ``get_decrypted_key`` across both credential kinds:
          * ``api_key`` → the decrypted pasted key.
          * ``oauth``   → a *fresh* access token; if it has expired and a
            refresh token is stored, it is refreshed (and re-persisted) first.

        Reserved for internal callers (chat pipeline). Bumps ``last_used_at``.
        Never exposed by an HTTP route.
        """
        try:
            oid = ObjectId(key_id)
        except (InvalidId, TypeError):
            return None
        doc = await self.collection.find_one({"_id": oid, "user_id": user_id})
        if not doc:
            return None

        if doc.get("credential_type") == "oauth":
            token = await self._fresh_oauth_token(doc)
            if token is None:
                return None
        else:
            try:
                token = decrypt(doc["encrypted_key"])
            except CryptoError:
                logger.warning(
                    "llm_key_service: failed to decrypt key id=%s user=%s",
                    key_id, user_id,
                )
                return None

        await self.collection.update_one(
            {"_id": oid}, {"$set": {"last_used_at": datetime.now(timezone.utc)}}
        )
        return token

    async def _fresh_oauth_token(self, doc: dict) -> Optional[str]:
        """Decrypt the stored access token, refreshing it first if expired."""
        try:
            access_token = decrypt(doc["encrypted_access_token"])
        except (CryptoError, KeyError):
            logger.warning("llm_key_service: failed to decrypt oauth token id=%s", doc.get("_id"))
            return None

        expires_at = doc.get("access_token_expires_at")
        enc_refresh = doc.get("encrypted_refresh_token")
        if not expires_at or not enc_refresh:
            # Non-expiring token (operator disabled token expiry) — use as-is.
            return access_token

        # Refresh slightly ahead of expiry to avoid mid-request 401s.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < (expires_at - timedelta(seconds=60)):
            return access_token

        try:
            refresh_token = decrypt(enc_refresh)
        except CryptoError:
            logger.warning("llm_key_service: failed to decrypt refresh token id=%s", doc.get("_id"))
            return access_token  # fall back to (possibly stale) access token

        if doc.get("provider") == "github_models":
            from app.services.github_oauth_service import refresh_github_token

            try:
                refreshed = await refresh_github_token(refresh_token)
            except Exception as exc:  # noqa: BLE001
                logger.warning("llm_key_service: github token refresh failed: %s", type(exc).__name__)
                return access_token
            new_access = refreshed.get("access_token")
            if not new_access:
                return access_token
            update: dict = {"encrypted_access_token": encrypt(new_access)}
            if refreshed.get("refresh_token"):
                update["encrypted_refresh_token"] = encrypt(refreshed["refresh_token"])
            if refreshed.get("expires_at"):
                update["access_token_expires_at"] = refreshed["expires_at"]
            await self.collection.update_one({"_id": doc["_id"]}, {"$set": update})
            return new_access

        return access_token

    # -------------------------------------------------------------------- test

    async def test_key(self, user_id: str, key_id: str) -> dict:
        """Fetch + decrypt + re-validate ``key_id``. Returns {ok, model}.

        Raises HTTPException 404 if the key is missing.
        Raises HTTPException 400 with a sanitised message on validation failure.
        """
        try:
            oid = ObjectId(key_id)
        except (InvalidId, TypeError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
            ) from None
        doc = await self.collection.find_one({"_id": oid, "user_id": user_id})
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
            )

        if doc.get("credential_type") == "oauth":
            plaintext = await self._fresh_oauth_token(doc)
            if not plaintext:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="OAuth token could not be refreshed or decrypted",
                )
        else:
            try:
                plaintext = decrypt(doc["encrypted_key"])
            except CryptoError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(exc),
                ) from None

        from advandeb_kb.services.llm_providers import get_provider
        from advandeb_kb.services.llm_providers.base import ProviderAuthError, ProviderError

        try:
            provider_instance = get_provider(doc["provider"], api_key=plaintext)
            ok = await provider_instance.validate()
        except ProviderAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"API key failed validation: {exc.message}",
            ) from None
        except ProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"API key failed validation: {exc.message}",
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"API key failed validation: {type(exc).__name__}",
            ) from None

        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API key failed validation",
            )

        # Update last_used_at on successful test.
        await self.collection.update_one(
            {"_id": oid}, {"$set": {"last_used_at": datetime.now(timezone.utc)}}
        )

        model = doc.get("default_model") or getattr(
            provider_instance, "default_model", ""
        )
        return {"ok": True, "model": model}
