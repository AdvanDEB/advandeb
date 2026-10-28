"""
Fernet-based symmetric encryption helper for BYOK secrets at rest.

The Fernet key itself lives in ``settings.LLM_KEY_ENCRYPTION_KEY`` and is
loaded lazily so the rest of the app can boot even when BYOK is disabled.

During a key rotation ``settings.LLM_KEY_ENCRYPTION_KEY_PREVIOUS`` lists the
retired keys: ciphertext under any of them still decrypts, while everything
newly encrypted uses the primary key (``MultiFernet``). See
scripts/rotate_llm_key_encryption.py.

Public API:
    encrypt(plaintext: str) -> str  # URL-safe base64 ciphertext
    decrypt(ciphertext: str) -> str
    CryptoError — raised on missing / invalid key or tampered ciphertext.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings


class CryptoError(Exception):
    """Raised on missing / malformed encryption key or undecryptable ciphertext."""


def _fernet() -> MultiFernet:
    key = settings.LLM_KEY_ENCRYPTION_KEY
    if not key:
        raise CryptoError(
            "LLM_KEY_ENCRYPTION_KEY is not set; BYOK features unavailable"
        )
    previous = [
        k.strip()
        for k in (settings.LLM_KEY_ENCRYPTION_KEY_PREVIOUS or "").split(",")
        if k.strip()
    ]
    try:
        # MultiFernet encrypts with the first key and decrypts with any.
        return MultiFernet([Fernet(k.encode()) for k in (key, *previous)])
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
