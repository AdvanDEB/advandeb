"""
OpenAI provider (BYOK).

Near-passthrough to the official ``openai`` async SDK. The SDK's response
objects are already in the OpenAI-compatible shape; we just call
``.model_dump()`` on them so callers get plain dicts.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from advandeb_kb.services.llm_providers.base import (
    BaseLLMProvider,
    ProviderAuthError,
    ProviderError,
)

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """OpenAI chat-completions provider using the ``openai`` async SDK."""

    provider_name = "openai"
    default_model = "gpt-4o"
    available_models = ["gpt-4o", "gpt-4o-mini", "o1-mini"]

    # Subclasses (e.g. GitHubModelsProvider) override these to repoint at
    # an OpenAI-compatible endpoint.
    _base_url: Optional[str] = None

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        if not api_key:
            raise ProviderAuthError(
                f"Missing API key for {self.provider_name}", self.provider_name
            )
        # Lazy import so the dep is only required when this provider is used.
        import openai  # type: ignore

        self._openai = openai
        self._api_key = api_key
        effective_base_url = base_url or self._base_url
        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if effective_base_url:
            client_kwargs["base_url"] = effective_base_url
        self._client = openai.AsyncOpenAI(**client_kwargs)

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
        call_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens
        # Pass through any caller-supplied extras (tools, response_format, ...).
        call_kwargs.update(kwargs)

        if stream:
            return self._stream(call_kwargs)

        try:
            resp = await self._client.chat.completions.create(**call_kwargs)
        except self._openai.AuthenticationError as e:
            raise ProviderAuthError(str(e), self.provider_name) from e
        except self._openai.APIStatusError as e:
            raise ProviderError(
                str(e), provider=self.provider_name, code=str(e.status_code)
            ) from e
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name) from e

        # SDK returns Pydantic models that already match the OpenAI shape.
        return resp.model_dump()

    async def _stream(self, call_kwargs: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        call_kwargs = {**call_kwargs, "stream": True}
        try:
            stream = await self._client.chat.completions.create(**call_kwargs)
            async for chunk in stream:
                yield chunk.model_dump()
        except self._openai.AuthenticationError as e:
            raise ProviderAuthError(str(e), self.provider_name) from e
        except self._openai.APIStatusError as e:
            raise ProviderError(
                str(e), provider=self.provider_name, code=str(e.status_code)
            ) from e
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name) from e

    #: Prefixes of chat-capable model families, used to filter the catalog
    #: (which also returns embeddings, TTS, image, and moderation models).
    _CHAT_MODEL_PREFIXES = ("gpt-", "chatgpt", "o1", "o3", "o4")

    async def list_models(self) -> List[str]:
        """Return the account's chat-capable model IDs, live.

        ``models.list()`` returns every model the key can see — including
        embeddings/audio/image models — so filter down to chat families and
        sort for a stable picker order.
        """
        try:
            resp = await self._client.models.list()
        except self._openai.AuthenticationError as e:
            raise ProviderAuthError(str(e), self.provider_name) from e
        except self._openai.APIStatusError as e:
            raise ProviderError(
                str(e), provider=self.provider_name, code=str(e.status_code)
            ) from e
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name) from e

        ids = [m.id for m in resp.data if getattr(m, "id", None)]
        chat = [i for i in ids if i.lower().startswith(self._CHAT_MODEL_PREFIXES)]
        # If the heuristic matched nothing (e.g. a custom deployment), don't
        # hide everything — fall back to the raw list.
        return sorted(chat or ids)

    async def validate(self) -> bool:
        # A successful authenticated list call proves the key works without
        # depending on any particular (possibly retired) model name.
        await self.list_models()
        return True

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:  # pragma: no cover - best-effort cleanup
                logger.debug("openai client close raised", exc_info=True)
