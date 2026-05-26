"""
LLMKeyService — encrypted per-user BYOK key storage + CRUD.

Storage layout (collection ``user_llm_keys`` in the app MongoDB):
    {
        _id:            ObjectId,
        user_id:        str   (str(ObjectId) of the owning user),
        provider:       str   ("anthropic" | "openai" | "gemini" | "github_models"),
        label:          str | None,
        default_model:  str | None,
        encrypted_key:  str   (Fernet ciphertext of the plaintext api key),
        key_last_4:     str   (last 4 chars of the plaintext, for UI display),
        created_at:     datetime (UTC),
        last_used_at:   datetime | None,
    }

The plaintext api_key is NEVER persisted, logged, or returned by any public
method except ``get_decrypted_key`` — which is reserved for internal callers
(e.g. the chat pipeline) that need to mint an outbound request.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
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
_BYOK_PROVIDER_NAMES = {"anthropic", "openai", "gemini", "github_models"}


def _doc_to_model(doc: dict) -> LLMKey:
    """Convert a stored Mongo document to the outbound ``LLMKey`` model."""
    return LLMKey(
        id=str(doc["_id"]),
        provider=doc["provider"],
        label=doc.get("label"),
        default_model=doc.get("default_model"),
        key_last_4=doc["key_last_4"],
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
        try:
            provider_instance = get_provider(provider, api_key=api_key)
            ok = await provider_instance.validate()
            if not ok:
                # Defensive — providers should raise, but in case validate()
                # returns False rather than raising, surface a 400.
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="API key failed validation",
                )
        except HTTPException:
            raise
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
