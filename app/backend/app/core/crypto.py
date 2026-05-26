"""
Fernet-based symmetric encryption helper for BYOK secrets at rest.

The Fernet key itself lives in ``settings.LLM_KEY_ENCRYPTION_KEY`` and is
loaded lazily so the rest of the app can boot even when BYOK is disabled.

Public API:
    encrypt(plaintext: str) -> str  # URL-safe base64 ciphertext
    decrypt(ciphertext: str) -> str
    CryptoError — raised on missing / invalid key or tampered ciphertext.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class CryptoError(Exception):
    """Raised on missing / malformed encryption key or undecryptable ciphertext."""


def _fernet() -> Fernet:
    key = settings.LLM_KEY_ENCRYPTION_KEY
    if not key:
        raise CryptoError(
            "LLM_KEY_ENCRYPTION_KEY is not set; BYOK features unavailable"
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # noqa: BLE001 - re-raised as CryptoError
        raise CryptoError(f"Invalid LLM_KEY_ENCRYPTION_KEY format: {exc}") from exc


def encrypt(plaintext: str) -> str:
    """Return URL-safe base64 Fernet ciphertext for ``plaintext``."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt ``ciphertext``; raises CryptoError on bad ciphertext / wrong key."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise CryptoError(
            "Failed to decrypt stored key (wrong key or tampered ciphertext)"
        ) from exc
