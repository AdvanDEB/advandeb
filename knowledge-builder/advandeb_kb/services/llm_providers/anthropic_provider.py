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

from advandeb_kb.config.settings import settings
from advandeb_kb.services.llm_providers.base import (
    BaseLLMProvider,
    ProviderAuthError,
    ProviderError,
)

logger = logging.getLogger(__name__)

# Models that support adaptive thinking + the `effort` control. Older Claude
# models (and any future ones we haven't tagged) gracefully skip it.
_ADAPTIVE_MODELS = ("opus-4-6", "opus-4-7", "opus-4-8", "sonnet-4-6", "fable-5", "mythos-5")


def _supports_adaptive(model: str) -> bool:
    m = (model or "").lower()
    return any(tag in m for tag in _ADAPTIVE_MODELS)


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


def _is_temperature_rejection(exc: Exception) -> bool:
    """True when an Anthropic 400 is about the `temperature` parameter.

    Some 2025+ Claude models deprecate `temperature`; the fix is to resend the
    request without it rather than fail the whole turn.
    """
    return "temperature" in str(exc).lower()


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
        kwargs_out: Dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }
        if system:
            kwargs_out["system"] = system

        # Adaptive thinking + effort for capable models. Capable models also
        # reject `temperature`, so drop it here (older models keep it).
        adaptive = settings.CHAT_ADAPTIVE_THINKING and _supports_adaptive(model)
        if adaptive:
            kwargs_out["thinking"] = {"type": "adaptive"}
            kwargs_out["output_config"] = {"effort": settings.CHAT_THINKING_EFFORT}
            kwargs_out.pop("temperature", None)

        try:
            try:
                resp = await self._final_message(kwargs_out)
            except self._anthropic.APIStatusError as e:
                # Graceful degradation: strip advanced params the model/SDK rejects
                # (adaptive thinking / effort), or `temperature` on newer models.
                changed = False
                if "thinking" in kwargs_out or "output_config" in kwargs_out:
                    kwargs_out.pop("thinking", None)
                    kwargs_out.pop("output_config", None)
                    changed = True
                if _is_temperature_rejection(e) and "temperature" in kwargs_out:
                    kwargs_out.pop("temperature", None)
                    changed = True
                if not changed:
                    raise
                resp = await self._final_message(kwargs_out)
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

    async def _final_message(self, kwargs_out: Dict[str, Any]):
        """Run a non-streaming request via the streaming API and return the final
        Message. Using ``messages.stream(...).get_final_message()`` instead of
        ``messages.create(...)`` avoids the SDK's non-streaming timeout guard, so
        large ``max_tokens`` (long answers, up to the model's 128K output) neither
        raise nor hit HTTP timeouts. The return value has the same shape as
        ``messages.create`` (``.content`` / ``.usage`` / ``.stop_reason``).
        """
        async with self._client.messages.stream(**kwargs_out) as stream_ctx:
            return await stream_ctx.get_final_message()

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
            try:
                async for chunk in self._emit_stream(kwargs_out, model):
                    yield chunk
                return
            except self._anthropic.APIStatusError as e:
                # Newer models reject `temperature`; the error is raised at stream
                # open before any chunk is emitted, so retrying is safe.
                if not (_is_temperature_rejection(e) and "temperature" in kwargs_out):
                    raise
                kwargs_out.pop("temperature", None)
            async for chunk in self._emit_stream(kwargs_out, model):
                yield chunk
        except self._anthropic.AuthenticationError as e:
            raise ProviderAuthError(str(e), self.provider_name) from e
        except self._anthropic.APIStatusError as e:
            raise ProviderError(
                str(e), provider=self.provider_name, code=str(e.status_code)
            ) from e
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name) from e

    async def _emit_stream(
        self, kwargs_out: Dict[str, Any], model: str
    ) -> AsyncIterator[Dict[str, Any]]:
        """One streaming attempt — yields OpenAI-compatible delta chunks."""
        async with self._client.messages.stream(**kwargs_out) as stream_ctx:
            async for text in stream_ctx.text_stream:
                if not text:
                    continue
                yield {
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {"content": text}, "finish_reason": None}
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

    async def list_models(self) -> List[str]:
        """Return the account's available Claude model IDs, live.

        ``client.models.list()`` auto-paginates; iterating it yields every
        model the key can see. Cheaper than a completion and never depends on a
        hardcoded (possibly retired) model name.
        """
        try:
            out: List[str] = []
            async for m in self._client.models.list():
                mid = getattr(m, "id", None)
                if mid:
                    out.append(mid)
            return out
        except self._anthropic.AuthenticationError as e:
            raise ProviderAuthError(str(e), self.provider_name) from e
        except self._anthropic.APIStatusError as e:
            raise ProviderError(
                str(e), provider=self.provider_name, code=str(e.status_code)
            ) from e
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name) from e

    async def validate(self) -> bool:
        # A successful authenticated list call proves the key works.
        await self.list_models()
        return True

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:  # pragma: no cover - best-effort cleanup
                logger.debug("anthropic client close raised", exc_info=True)
