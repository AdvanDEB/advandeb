"""
Pydantic models for per-user BYOK LLM API keys.

``LLMKeyCreate`` is the inbound POST body (contains the plaintext ``api_key``).
``LLMKey``       is the outbound representation: plaintext is NEVER returned —
                  only the last four characters of the key, for UI display.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LLMKeyCreate(BaseModel):
    """Inbound payload for POST /api/users/me/llm-keys."""

    provider: str
    api_key: str = Field(..., min_length=4)
    label: Optional[str] = None
    default_model: Optional[str] = None


class LLMKey(BaseModel):
    """Outbound representation of a stored BYOK key (no plaintext)."""

    id: str
    provider: str
    label: Optional[str] = None
    default_model: Optional[str] = None
    key_last_4: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
