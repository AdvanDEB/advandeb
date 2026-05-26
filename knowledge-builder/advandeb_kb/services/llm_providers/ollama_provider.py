"""
Ollama provider — thin BYOK-shaped wrapper around the existing
``OllamaModelProvider`` in ``local_model_provider.py``.

This adapter exists so the registry can return a single uniform
``BaseLLMProvider`` regardless of whether the user runs locally on Ollama or
brings their own cloud API key.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from advandeb_kb.services.llm_providers.base import (
    BaseLLMProvider,
    ProviderError,
)

logger = logging.getLogger(__name__)


class OllamaProvider(BaseLLMProvider):
    """BYOK wrapper around local Ollama (no API key required)."""

    provider_name = "ollama"
    default_model = "deepseek-r1:latest"
    available_models = [
        "deepseek-r1:latest",
        "gemma3:latest",
        "llama3:latest",
    ]

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        # api_key is accepted for signature symmetry but ignored.
        # Lazy import keeps the dependency graph clean even though Ollama
        # support is always available (no extra SDK needed).
        from advandeb_kb.services.local_model_provider import OllamaModelProvider

        self._inner = OllamaModelProvider(base_url=base_url)
        self.base_url = self._inner.base_url

    async def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        *,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            return await self._inner.chat_completion(
                model=model,
                messages=messages,
                stream=stream,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                str(e), provider=self.provider_name, code=str(e.response.status_code)
            ) from e
        except Exception as e:  # pragma: no cover - defensive
            raise ProviderError(str(e), provider=self.provider_name) from e

    async def validate(self) -> bool:
        """Ping ``/api/tags`` to confirm the Ollama daemon is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Ollama returned HTTP {e.response.status_code}",
                provider=self.provider_name,
                code=str(e.response.status_code),
            ) from e
        except Exception as e:
            raise ProviderError(
                f"Could not reach Ollama at {self.base_url}: {e}",
                provider=self.provider_name,
                code="unreachable",
            ) from e

    async def close(self) -> None:
        await self._inner.client.aclose()
