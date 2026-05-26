"""
BYOK (Bring-Your-Own-Key) LLM provider abstraction.

Exposes a uniform ``BaseLLMProvider`` interface so chat / agent code can talk
to Ollama, Anthropic, OpenAI, Gemini, or GitHub Models without caring which
backend is active.
"""
from advandeb_kb.services.llm_providers.base import (
    BaseLLMProvider,
    ProviderAuthError,
    ProviderError,
)
from advandeb_kb.services.llm_providers.registry import (
    PROVIDERS,
    get_provider,
    list_providers,
)

__all__ = [
    "BaseLLMProvider",
    "ProviderError",
    "ProviderAuthError",
    "get_provider",
    "list_providers",
    "PROVIDERS",
]
