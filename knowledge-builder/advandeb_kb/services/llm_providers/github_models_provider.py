"""
GitHub Models provider (BYOK).

GitHub's hosted model catalog at ``https://models.github.ai/inference`` is
OpenAI-compatible at the wire level, so we subclass ``OpenAIProvider`` and just
point the ``openai`` SDK at that base URL using a GitHub token as the bearer.

The token can be either a fine-grained PAT with the ``models:read`` permission
(pasted by the user) or a GitHub App user token obtained via the device flow
("Connect with GitHub"). Either way it is sent as ``Authorization: Bearer``.
Model IDs are ``publisher/model`` (e.g. ``openai/gpt-4o``).
"""
from __future__ import annotations

from typing import List, Optional

from advandeb_kb.services.llm_providers.base import ProviderAuthError, ProviderError
from advandeb_kb.services.llm_providers.openai_provider import OpenAIProvider


class GitHubModelsProvider(OpenAIProvider):
    """OpenAI-compatible client pointed at GitHub Models."""

    provider_name = "github_models"
    default_model = "openai/gpt-4o-mini"
    available_models = [
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/gpt-4.1",
        "openai/gpt-4.1-mini",
    ]

    # Override the OpenAI base URL (current GitHub Models inference endpoint).
    _base_url = "https://models.github.ai/inference"

    # Live model list comes from the catalog API, not the inference endpoint
    # (which has no OpenAI-style ``/models`` route).
    _catalog_url = "https://models.github.ai/catalog/models"

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        # ``api_key`` here is a GitHub token (fine-grained PAT with models:read,
        # or a device-flow user token); the openai SDK passes it as
        # ``Authorization: Bearer <token>`` which GitHub Models accepts.
        super().__init__(api_key=api_key, base_url=base_url or self._base_url)

    async def list_models(self) -> List[str]:
        """Return GitHub Models' chat model IDs (``publisher/model``), live.

        The inference base URL has no ``/models`` route, so query the catalog
        API with the GitHub token as a bearer. Embedding-only models are
        filtered out so they don't pollute the chat picker.
        """
        import httpx

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(self._catalog_url, headers=headers)
            if resp.status_code in (401, 403):
                raise ProviderAuthError(
                    f"GitHub rejected the token ({resp.status_code})", self.provider_name
                )
            resp.raise_for_status()
            items = resp.json()
        except ProviderAuthError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ProviderError(str(e), provider=self.provider_name) from e

        out: List[str] = []
        for item in items if isinstance(items, list) else []:
            mid = item.get("id") if isinstance(item, dict) else None
            if not mid:
                continue
            outputs = item.get("supported_output_modalities") or []
            # Keep chat-capable models: those that can emit text, or — when the
            # field is absent — anything that isn't an embedding model.
            if outputs:
                if "text" in outputs:
                    out.append(mid)
            elif "embedding" not in mid.lower():
                out.append(mid)
        return sorted(out)
