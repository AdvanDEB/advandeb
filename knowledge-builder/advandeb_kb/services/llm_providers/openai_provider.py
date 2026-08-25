"""
OpenAI provider (BYOK).

Near-passthrough to the official ``openai`` async SDK. The SDK's response
objects are already in the OpenAI-compatible shape; we just call
``.model_dump()`` on them so callers get plain dicts.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from advandeb_kb.config.settings import settings
from advandeb_kb.services.llm_providers.base import (
    BaseLLMProvider,
    ProviderAuthError,
    ProviderError,
)

logger = logging.getLogger(__name__)


def _to_openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert unified message list (may include tool-call turns) to OpenAI API format.

    Unified tool_calls use ``{"id", "name", "input": {...}}``; OpenAI requires
    ``{"id", "type": "function", "function": {"name", "arguments": json_str}}``.
    Tool-result turns stay the same shape (role: "tool", tool_call_id, content).
    """
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content")
        if role == "system":
            out.append({"role": "system", "content": content or ""})
        elif role == "user":
            out.append({"role": "user", "content": content or ""})
        elif role == "assistant":
            tool_calls = m.get("tool_calls") or []
            if tool_calls:
                oai_tcs = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc.get("input", {})),
                        },
                    }
                    for tc in tool_calls
                ]
                out.append({"role": "assistant", "content": content or None, "tool_calls": oai_tcs})
            else:
                out.append({"role": "assistant", "content": content or ""})
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id", ""), "content": content or ""})
    return out


class OpenAIProvider(BaseLLMProvider):
    """OpenAI chat-completions provider using the ``openai`` async SDK."""

    provider_name = "openai"
    default_model = "gpt-4o"
    supports_tools = True
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

        # Reasoning-effort for reasoning-capable models (o-series, gpt-5, …).
        # Non-reasoning models reject it → we strip and retry (graceful no-op).
        if settings.CHAT_ADAPTIVE_THINKING and "reasoning_effort" not in call_kwargs:
            call_kwargs["reasoning_effort"] = settings.CHAT_THINKING_EFFORT

        if stream:
            return self._stream(call_kwargs)

        try:
            resp = await self._create_with_retry(call_kwargs)
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

    async def _create_with_retry(self, call_kwargs: Dict[str, Any], *, max_retries: int = 4):
        """Call chat.completions.create with exponential backoff on 429 / ResourceExhausted.

        NIM worker-concurrency errors (status 429, body contains "ResourceExhausted"
        or "limit reached") are transient — a short wait is enough to clear them.
        Delays: 5 s, 15 s, 30 s, 60 s before giving up.
        """
        delays = [5, 15, 30, 60]
        last_exc: Exception | None = None

        # First try: with reasoning_effort if configured; strip and retry once on 400.
        try:
            return await self._client.chat.completions.create(**call_kwargs)
        except self._openai.APIStatusError as e:
            if "reasoning_effort" in call_kwargs and e.status_code == 400:
                call_kwargs = {k: v for k, v in call_kwargs.items() if k != "reasoning_effort"}
            elif self._is_rate_limit(e):
                last_exc = e
            else:
                raise

        for delay in delays:
            if last_exc is None:
                # Previous error was a non-rate-limit (e.g. reasoning_effort stripped);
                # retry once immediately.
                try:
                    return await self._client.chat.completions.create(**call_kwargs)
                except self._openai.APIStatusError as e:
                    if not self._is_rate_limit(e):
                        raise
                    last_exc = e

            logger.warning(
                "%s rate-limited (ResourceExhausted); retrying in %ds", self.provider_name, delay
            )
            await asyncio.sleep(delay)
            try:
                return await self._client.chat.completions.create(**call_kwargs)
            except self._openai.APIStatusError as e:
                if not self._is_rate_limit(e):
                    raise
                last_exc = e

        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        """True for 429 / ResourceExhausted / worker-limit errors."""
        status = getattr(exc, "status_code", None)
        body = str(exc).lower()
        return status == 429 or "resourceexhausted" in body or "limit reached" in body

    async def _stream(self, call_kwargs: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        call_kwargs = {**call_kwargs, "stream": True}
        # Strip reasoning_effort on stream open if the first attempt fails with 400.
        try:
            stream = await self._client.chat.completions.create(**call_kwargs)
        except self._openai.APIStatusError as e:
            if "reasoning_effort" in call_kwargs and e.status_code == 400:
                call_kwargs = {k: v for k, v in call_kwargs.items() if k != "reasoning_effort"}
                stream = await self._client.chat.completions.create(**call_kwargs)
            elif self._is_rate_limit(e):
                # For streaming, wait once then retry (complex multi-retry not worth it).
                logger.warning("%s stream rate-limited; waiting 15s", self.provider_name)
                await asyncio.sleep(15)
                stream = await self._client.chat.completions.create(**call_kwargs)
            else:
                raise ProviderError(str(e), provider=self.provider_name, code=str(e.status_code)) from e
        try:
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

    async def chat_with_tools(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        *,
        max_tokens: int = 8192,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """Single step in an OpenAI tool-calling conversation.

        The OpenAI tool format matches our unified format closely, so minimal
        translation is needed. Converts tool-result messages to the role="tool"
        shape the API expects and returns a unified response dict.
        """
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

        # Translate assistant messages with our tool_calls format to OpenAI format.
        adapted: List[Dict[str, Any]] = []
        for m in messages:
            role = m.get("role", "")
            if role == "assistant" and m.get("tool_calls"):
                adapted.append({
                    "role": "assistant",
                    "content": m.get("content") or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["input"]),
                            },
                        }
                        for tc in m["tool_calls"]
                    ],
                })
            elif role == "tool":
                adapted.append({
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                })
            else:
                adapted.append({"role": role, "content": m.get("content", "")})

        call_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": adapted,
            "tools": openai_tools,
            "tool_choice": "auto",
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

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

        choice = resp.choices[0]
        msg = choice.message
        tool_calls: List[Dict[str, Any]] = []
        if choice.finish_reason == "tool_calls" and msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    inp = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    inp = {}
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": inp,
                })

        return {
            "finish_reason": "tool_calls" if tool_calls else (choice.finish_reason or "stop"),
            "content": msg.content or "",
            "tool_calls": tool_calls,
        }

    #: Prefixes of chat-capable model families, used to filter the catalog
    #: (which also returns embeddings, TTS, image, and moderation models).
    _CHAT_MODEL_PREFIXES = ("gpt-", "chatgpt", "o1", "o3", "o4")

    async def stream_final_answer(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """Stream the final synthesis given conversation history including tool turns.

        Converts the unified message format (tool_calls with ``input`` dicts) to
        the OpenAI wire format and streams the response, yielding plain text deltas.
        Called after the agentic tool loop so the LLM can write a streaming answer
        with full evidence context.
        """
        oai_msgs = _to_openai_messages(messages)
        call_kwargs: Dict[str, Any] = {"model": model, "messages": oai_msgs, "temperature": temperature}
        if max_tokens:
            call_kwargs["max_tokens"] = max_tokens
        try:
            async for chunk in self._stream(call_kwargs):
                try:
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
                except (IndexError, AttributeError):
                    delta = ""
                if delta:
                    yield delta
        except self._openai.AuthenticationError as e:
            raise ProviderAuthError(str(e), self.provider_name) from e
        except self._openai.APIStatusError as e:
            raise ProviderError(str(e), provider=self.provider_name, code=str(e.status_code)) from e
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name) from e

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
