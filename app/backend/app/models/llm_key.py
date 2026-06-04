"""
Pydantic models for per-user BYOK LLM credentials.

A stored credential is one of two kinds, distinguished by ``credential_type``:

  * ``"api_key"`` — a pasted secret (the original BYOK path). Only the last
    four characters are ever returned, via ``key_last_4``.
  * ``"oauth"``   — a token obtained through a sanctioned OAuth device flow
    (e.g. "Connect with GitHub" → GitHub Models). No secret is returned; the
    UI shows ``account_label`` (e.g. the GitHub login) instead.

``LLMKeyCreate`` is the inbound POST body for the pasted-key path. ``LLMKey``
is the outbound representation for both kinds: plaintext / tokens are NEVER
returned.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class LLMKeyCreate(BaseModel):
    """Inbound payload for POST /api/users/me/llm-keys."""

    provider: str
    api_key: str = Field(..., min_length=4)
    label: Optional[str] = None
    default_model: Optional[str] = None


class LLMKey(BaseModel):
    """Outbound representation of a stored BYOK credential (no secret)."""

    id: str
    provider: str
    credential_type: Literal["api_key", "oauth"] = "api_key"
    label: Optional[str] = None
    default_model: Optional[str] = None
    #: Last 4 chars of a pasted key — present only for ``credential_type == "api_key"``.
    key_last_4: Optional[str] = None
    #: Connected account identifier (e.g. GitHub login) — present for OAuth rows.
    account_label: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None
