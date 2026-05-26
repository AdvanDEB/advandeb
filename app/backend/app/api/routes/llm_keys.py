"""
BYOK LLM key management routes — mounted under ``/api/users/me/llm-keys``.

Every route is scoped to the authenticated user via ``get_current_user``; a
user can only ever see / mutate their own keys. The plaintext API key flows in
on POST and is never returned: list/create responses carry only ``key_last_4``.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.auth import get_current_user
from app.core.limiter import limiter
from app.models.llm_key import LLMKey, LLMKeyCreate
from app.services.llm_key_service import LLMKeyService

router = APIRouter()


@router.get("/providers")
async def list_supported_providers(current_user: dict = Depends(get_current_user)):
    """Return the catalog of BYOK providers + their available models.

    Used by the UI to populate the provider/model pickers. Excludes ``ollama``
    (local, no key to store) — only key-bearing providers are listed.
    """
    from advandeb_kb.services.llm_providers import list_providers

    byok = {"anthropic", "openai", "gemini", "github_models"}
    return [p for p in list_providers() if p["name"] in byok]


@router.get("", response_model=List[LLMKey])
async def list_my_keys(current_user: dict = Depends(get_current_user)):
    """List the current user's stored BYOK keys (no plaintext)."""
    return await LLMKeyService().list_keys(current_user["id"])


@router.post("", response_model=LLMKey, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def create_my_key(
    request: Request,
    body: LLMKeyCreate,
    current_user: dict = Depends(get_current_user),
):
    """Validate, encrypt, and store a new BYOK key for the current user."""
    return await LLMKeyService().create_key(
        user_id=current_user["id"],
        provider=body.provider,
        api_key=body.api_key,
        label=body.label,
        default_model=body.default_model,
    )


@router.post("/{key_id}/test")
@limiter.limit("5/minute")
async def test_my_key(
    request: Request,
    key_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Re-validate a stored key against its provider. Returns {ok, model}."""
    return await LLMKeyService().test_key(current_user["id"], key_id)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_key(
    key_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a stored key the current user owns."""
    deleted = await LLMKeyService().delete_key(current_user["id"], key_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Key not found"
        )
