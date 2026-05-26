"""
GitHub Models provider (BYOK).

GitHub's hosted model catalog at ``https://models.inference.ai.azure.com`` is
OpenAI-compatible at the wire level, so we subclass ``OpenAIProvider`` and
just point the ``openai`` SDK at that base URL using the user's GitHub PAT
as the bearer token.
"""
from __future__ import annotations

from typing import Optional

from advandeb_kb.services.llm_providers.openai_provider import OpenAIProvider


class GitHubModelsProvider(OpenAIProvider):
    """OpenAI-compatible client pointed at GitHub Models."""

    provider_name = "github_models"
    default_model = "gpt-4o"
    available_models = [
        "gpt-4o",
        "gpt-4o-mini",
        "Meta-Llama-3-1-70B-Instruct",
        "Phi-3-5-MoE-instruct",
    ]

    # Override the OpenAI base URL.
    _base_url = "https://models.inference.ai.azure.com"

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        # ``api_key`` here is the user's GitHub PAT; the openai SDK passes it
        # as ``Authorization: Bearer <pat>`` which GitHub Models accepts.
        super().__init__(api_key=api_key, base_url=base_url or self._base_url)
