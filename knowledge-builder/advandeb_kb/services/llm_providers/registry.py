"""
Provider registry / factory.

Centralises the mapping from short provider slug (used by the UI and stored
alongside the encrypted API key) to the concrete ``BaseLLMProvider``
implementation.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Type

from advandeb_kb.services.llm_providers.anthropic_provider import AnthropicProvider
from advandeb_kb.services.llm_providers.base import BaseLLMProvider
from advandeb_kb.services.llm_providers.gemini_provider import GeminiProvider
from advandeb_kb.services.llm_providers.github_models_provider import (
    GitHubModelsProvider,
)
from advandeb_kb.services.llm_providers.ollama_provider import OllamaProvider
from advandeb_kb.services.llm_providers.openai_provider import OpenAIProvider

PROVIDERS: Dict[str, Type[BaseLLMProvider]] = {
    "ollama": OllamaProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "github_models": GitHubModelsProvider,
}


def get_provider(name: str, api_key: Optional[str] = None) -> BaseLLMProvider:
    """Instantiate a provider by slug.

    ``api_key`` is ignored for ``ollama`` and required for every other
    provider. Raises ``KeyError`` if ``name`` isn't registered.
    """
    cls = PROVIDERS[name]
    if name == "ollama":
        return cls()
    return cls(api_key=api_key)


def list_providers() -> List[dict]:
    """Return a UI-friendly summary of every registered provider."""
    return [
        {
            "name": cls.provider_name,
            "default_model": cls.default_model,
            "available_models": list(cls.available_models),
        }
        for cls in PROVIDERS.values()
    ]
