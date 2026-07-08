"""
Base abstract class for BYOK (Bring-Your-Own-Key) LLM providers.

Every provider implementation must conform to the OpenAI-compatible response
shape so that downstream chat / agent code can stay provider-agnostic:

    {
        "id": "...",
        "choices": [
            {"message": {"role": "assistant", "content": "..."},
             "finish_reason": "..."}
        ],
        "usage": {"prompt_tokens": int,
                  "completion_tokens": int,
                  "total_tokens": int},
        "model": "...",
    }

When ``stream=True`` is requested, the provider must return an async iterator
of partial deltas in the OpenAI streaming shape:

    {"choices": [{"delta": {"content": "..."}, "finish_reason": None}]}
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, List, Optional


class ProviderError(Exception):
    """Generic provider-layer error.

    Wraps SDK / HTTP exceptions so callers don't have to import each vendor's
    error hierarchy. Carries a short, vendor-neutral ``code`` plus the original
    message.
    """

    def __init__(self, message: str, provider: str, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.code = code

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.provider}:{self.code or 'error'}] {self.message}"


class ProviderAuthError(ProviderError):
    """Raised when credentials are missing or invalid (HTTP 401 equivalent)."""

    def __init__(self, message: str, provider: str):
        super().__init__(message, provider, code="auth")


class BaseLLMProvider(ABC):
    """Abstract base for all chat-completion providers."""

    #: Short slug identifying the provider (e.g. "anthropic", "openai").
    provider_name: ClassVar[str] = ""

    #: Default model used by ``validate()`` and when the caller omits ``model``.
    default_model: ClassVar[str] = ""

    #: Curated short list of models exposed to the UI for this provider.
    available_models: ClassVar[List[str]] = []

    #: True when the provider supports native tool / function calling.
    #: Providers that set this must also implement ``chat_with_tools()``.
    supports_tools: ClassVar[bool] = False

    @abstractmethod
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
        """Run a chat completion.

        Returns either a single OpenAI-compatible response dict, or — when
        ``stream=True`` — an async iterator of OpenAI-compatible delta dicts.
        """

    @abstractmethod
    async def validate(self) -> bool:
        """Make a minimal test call to confirm credentials work.

        Returns ``True`` on success; raises ``ProviderAuthError`` /
        ``ProviderError`` on failure. Called by the key-storage layer at
        insert time so we never persist invalid keys.
        """

    async def chat_with_tools(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        *,
        max_tokens: int = 8192,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """Single step in a tool-calling conversation.

        ``tools`` is a list of tool-definition dicts with keys:
            name, description, input_schema (JSON Schema object).

        ``messages`` may contain tool_call / tool-result turns in our unified
        format::

            # assistant turn that called tools
            {"role": "assistant", "content": "...", "tool_calls": [
                {"id": "tc1", "name": "search_kb", "input": {...}}
            ]}
            # tool result
            {"role": "tool", "tool_call_id": "tc1", "content": "...result..."}

        Returns a dict with:
            finish_reason: "stop" | "tool_calls"
            content:       text produced by the model (may be empty string)
            tool_calls:    list of {id, name, input} (empty unless finish_reason == "tool_calls")
        """
        raise NotImplementedError(
            f"{self.provider_name} does not implement tool calling; "
            "set supports_tools=True and override chat_with_tools()."
        )

    async def list_models(self) -> List[str]:
        """Return the chat model IDs this credential can actually use.

        The default implementation returns the curated, hardcoded
        ``available_models`` — used as an offline fallback and for providers
        with no live catalog. Network-backed providers override this to query
        the vendor's live model list so the UI never offers a retired model
        (the original cause of the ``gemini-1.5-flash`` 404s).

        Implementations that hit the network should raise ``ProviderAuthError``
        on bad credentials so this method can double as a key validator.
        """
        return list(self.available_models)

    @abstractmethod
    async def close(self) -> None:
        """Release any underlying SDK / httpx client resources."""

    async def __aenter__(self) -> "BaseLLMProvider":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
