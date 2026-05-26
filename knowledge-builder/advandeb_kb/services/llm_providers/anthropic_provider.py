"""
Anthropic Claude provider (BYOK).

Adapts the OpenAI-style ``messages=[{"role","content"}, ...]`` input to
Anthropic's API which takes ``system`` separately from ``messages`` and
returns content as a list of blocks. The response is translated back to the
OpenAI-compatible shape used by the rest of the codebase.
"""
from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from advandeb_kb.services.llm_providers.base import (
    BaseLLMProvider,
    ProviderAuthError,
    ProviderError,
)

logger = logging.getLogger(__name__)


def _split_system(messages: List[Dict[str, str]]) -> Tuple[Optional[str], List[Dict[str, str]]]:
    """Pull leading system messages out into a single system string.

    Multiple system messages (uncommon, but legal in OpenAI shape) are joined
    with double newlines. Non-leading system messages are also collapsed in.
    """
    system_parts: List[str] = []
    rest: List[Dict[str, str]] = []
    for m in messages:
        if m.get("role") == "system":
            content = m.get("content", "")
            if content:
                system_parts.append(content)
        else:
            rest.append({"role": m["role"], "content": m.get("content", "")})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, rest


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude provider using the ``anthropic`` async SDK."""

    provider_name = "anthropic"
    default_model = "claude-opus-4-7"
    available_models = [
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ]

    def __init__(self, api_key: str):
        if not api_key:
            raise ProviderAuthError("Missing Anthropic API key", self.provider_name)
        # Lazy import so the dep is only required when this provider is used.
        import anthropic  # type: ignore

        self._anthropic = anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

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
        system, msgs = _split_system(messages)
        # Anthropic requires max_tokens; pick a sane default.
        effective_max_tokens = max_tokens if max_tokens is not None else 1024

        if stream:
            return self._stream(
                model=model,
                system=system,
                msgs=msgs,
                temperature=temperature,
                max_tokens=effective_max_tokens,
            )
        try:
            kwargs_out: Dict[str, Any] = {
                "model": model,
                "messages": msgs,
                "temperature": temperature,
                "max_tokens": effective_max_tokens,
            }
            if system:
                kwargs_out["system"] = system
            resp = await self._client.messages.create(**kwargs_out)
        except self._anthropic.AuthenticationError as e:
            raise ProviderAuthError(str(e), self.provider_name) from e
        except self._anthropic.APIStatusError as e:
            raise ProviderError(
                str(e), provider=self.provider_name, code=str(e.status_code)
            ) from e
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name) from e

        text_parts = [
            getattr(b, "text", "") for b in (resp.content or []) if getattr(b, "type", "") == "text"
        ]
        content = "".join(text_parts)
        in_tok = getattr(resp.usage, "input_tokens", 0) if resp.usage else 0
        out_tok = getattr(resp.usage, "output_tokens", 0) if resp.usage else 0
        return {
            "id": resp.id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": resp.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": resp.stop_reason or "stop",
                }
            ],
            "usage": {
                "prompt_tokens": in_tok,
                "completion_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
            },
        }

    async def _stream(
        self,
        *,
        model: str,
        system: Optional[str],
        msgs: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[Dict[str, Any]]:
        kwargs_out: Dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            kwargs_out["system"] = system
        try:
            async with self._client.messages.stream(**kwargs_out) as stream_ctx:
                async for text in stream_ctx.text_stream:
                    if not text:
                        continue
                    yield {
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": text},
                                "finish_reason": None,
                            }
                        ],
                    }
                final = await stream_ctx.get_final_message()
            yield {
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": (final.stop_reason if final else "stop") or "stop",
                    }
                ],
            }
        except self._anthropic.AuthenticationError as e:
            raise ProviderAuthError(str(e), self.provider_name) from e
        except self._anthropic.APIStatusError as e:
            raise ProviderError(
                str(e), provider=self.provider_name, code=str(e.status_code)
            ) from e
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name) from e

    async def validate(self) -> bool:
        try:
            await self._client.messages.create(
                model=self.default_model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except self._anthropic.AuthenticationError as e:
            raise ProviderAuthError(str(e), self.provider_name) from e
        except self._anthropic.APIStatusError as e:
            raise ProviderError(
                str(e), provider=self.provider_name, code=str(e.status_code)
            ) from e
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name) from e

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:  # pragma: no cover - best-effort cleanup
                logger.debug("anthropic client close raised", exc_info=True)
