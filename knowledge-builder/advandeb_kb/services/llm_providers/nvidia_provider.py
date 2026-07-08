"""
NVIDIA NIM provider.

NVIDIA's Inference Microservices (NIM) endpoint is OpenAI-compatible, so we
subclass OpenAIProvider and repoint at the NIM base URL. API keys are NGC API
keys (``nvapi-...``).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from advandeb_kb.services.llm_providers.base import ProviderError
from advandeb_kb.services.llm_providers.openai_provider import OpenAIProvider, _to_openai_messages

logger = logging.getLogger(__name__)


class NvidiaProvider(OpenAIProvider):
    """OpenAI-compatible client pointed at NVIDIA NIM."""

    provider_name = "nvidia"
    default_model = "nvidia/nemotron-3-ultra-550b-a55b"
    # The 550B Ultra model supports function calling reliably on NIM.
    # Smaller NIM models (mini, 70b) may not — they remain behind supports_tools=False
    # if instantiated directly, but this class targets the 550B default.
    supports_tools = True
    available_models = [
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/llama-3.3-nemotron-super-49b-v1",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "nvidia/nemotron-mini-4b-instruct",
    ]

    _base_url = "https://integrate.api.nvidia.com/v1"

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        super().__init__(api_key=api_key, base_url=base_url or self._base_url)

    async def chat_with_tools(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        *,
        max_tokens: int = 8192,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """Tool-calling with automatic fallback for NIM DEGRADED / unavailable errors.

        When NIM reports the function endpoint is degraded (HTTP 400 "DEGRADED
        function cannot be invoked"), tool calling is not available for this
        model at this moment. Instead of failing, fall back to a plain (no-tool)
        completion so the agentic loop can still produce a final answer.
        """
        try:
            return await super().chat_with_tools(
                model, messages, tools, max_tokens=max_tokens, temperature=temperature
            )
        except ProviderError as exc:
            body = str(exc).lower()
            if "degraded" in body or "cannot be invoked" in body:
                logger.warning(
                    "nvidia: model %s degraded for tool calling — falling back to plain completion",
                    model,
                )
                # Plain completion: strip tool-call turns from history (they'd
                # be empty at this point since no tools ran yet) and get text.
                plain_msgs = _to_openai_messages(messages)
                resp = await self._create_with_retry(
                    {"model": model, "messages": plain_msgs,
                     "temperature": temperature, "max_tokens": max_tokens}
                )
                try:
                    content = resp.choices[0].message.content or ""
                except Exception:
                    content = ""
                return {"finish_reason": "stop", "content": content, "tool_calls": []}
            raise

    async def list_models(self) -> List[str]:
        # NIM doesn't expose a compatible /models route; return known list.
        return list(self.available_models)

    async def validate(self) -> bool:
        # Can't enumerate models live; trust the key format as a proxy.
        return bool(self._api_key)
