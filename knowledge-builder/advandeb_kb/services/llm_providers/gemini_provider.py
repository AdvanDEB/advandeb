"""
Google Gemini provider (BYOK).

Gemini's chat API differs from OpenAI's in three ways that this adapter has
to bridge:

1. Messages use ``parts=[{"text": ...}]`` instead of a flat ``content`` string.
2. The assistant role is named ``model`` (we map ``assistant`` <-> ``model``).
3. System prompts are passed once via ``system_instruction`` in the request
   config, not as a message in the conversation.

Responses are translated back into the OpenAI-compatible shape used
throughout the codebase.
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


def _to_gemini_messages(
    messages: List[Dict[str, str]],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Translate OpenAI messages into (system_instruction, gemini_messages)."""
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "") or ""
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        gemini_role = "model" if role == "assistant" else "user"
        out.append({"role": gemini_role, "parts": [{"text": content}]})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, out


def _extract_text(response: Any) -> str:
    """Extract concatenated text from a Gemini ``GenerateContentResponse``."""
    # ``response.text`` is a convenience accessor on the SDK type, but it
    # raises if there are zero text parts — guard with ``getattr`` and fall
    # back to walking ``candidates[*].content.parts``.
    try:
        text = getattr(response, "text", None)
        if text:
            return text
    except Exception:
        pass
    parts_text: List[str] = []
    for cand in getattr(response, "candidates", []) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", []) or []:
            t = getattr(part, "text", None)
            if t:
                parts_text.append(t)
    return "".join(parts_text)


def _usage_dict(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    p = getattr(usage, "prompt_token_count", 0) or 0
    c = getattr(usage, "candidates_token_count", 0) or 0
    t = getattr(usage, "total_token_count", p + c) or (p + c)
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": t}


def _finish_reason(response: Any) -> str:
    cands = getattr(response, "candidates", None) or []
    if not cands:
        return "stop"
    fr = getattr(cands[0], "finish_reason", None)
    if fr is None:
        return "stop"
    # SDK returns an enum; ``.name`` gives a readable label.
    name = getattr(fr, "name", str(fr))
    return name.lower() if isinstance(name, str) else "stop"


class GeminiProvider(BaseLLMProvider):
    """Gemini chat provider using the ``google-genai`` SDK."""

    provider_name = "gemini"
    # Offline fallback only — the live catalog is fetched via list_models().
    # Kept current so the UI is sane even before a key is entered.
    default_model = "gemini-2.5-flash"
    available_models = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
    ]

    def __init__(self, api_key: str):
        if not api_key:
            raise ProviderAuthError("Missing Gemini API key", self.provider_name)
        # Lazy import.
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore

        self._types = types
        self._api_key = api_key
        # The key belongs to this client. (google-generativeai configured it
        # process-wide, so two users' concurrent requests could swap keys.)
        self._client = genai.Client(api_key=api_key)

    def _generation_config(
        self,
        system_instruction: Optional[str],
        temperature: float,
        max_tokens: Optional[int],
    ) -> Any:
        cfg: Dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            cfg["max_output_tokens"] = max_tokens
        if system_instruction:
            cfg["system_instruction"] = system_instruction
        return self._types.GenerateContentConfig(**cfg)

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
        system, gemini_msgs = _to_gemini_messages(messages)
        config = self._generation_config(system, temperature, max_tokens)

        if stream:
            return self._stream(gemini_msgs, config, model)

        try:
            response = await self._client.aio.models.generate_content(
                model=model, contents=gemini_msgs, config=config
            )
        except Exception as e:
            self._raise_translated(e)

        return {
            "id": f"gemini-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": _extract_text(response)},
                    "finish_reason": _finish_reason(response),
                }
            ],
            "usage": _usage_dict(response),
        }

    async def _stream(
        self,
        gemini_msgs: List[Dict[str, Any]],
        config: Any,
        model_name: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        try:
            chunks = await self._client.aio.models.generate_content_stream(
                model=model_name, contents=gemini_msgs, config=config
            )
        except Exception as e:
            self._raise_translated(e)
            return  # pragma: no cover - _raise_translated always raises

        try:
            async for chunk in chunks:
                text = _extract_text(chunk)
                if not text:
                    continue
                yield {
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": text},
                            "finish_reason": None,
                        }
                    ],
                }
        except Exception as e:
            self._raise_translated(e)

        yield {
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }

    async def list_models(self) -> List[str]:
        """Return Gemini models that support ``generateContent``, live.

        Model names come back as ``models/<id>``; strip the prefix to match
        what callers pass to ``generate_content``.
        """
        out: List[str] = []
        try:
            async for m in await self._client.aio.models.list():
                actions = getattr(m, "supported_actions", None) or []
                if "generateContent" not in actions:
                    continue
                name = getattr(m, "name", "") or ""
                out.append(name[len("models/"):] if name.startswith("models/") else name)
        except Exception as e:
            self._raise_translated(e)
        return out

    async def validate(self) -> bool:
        # A successful authenticated list call proves the key works without
        # depending on any particular (possibly retired) model name.
        await self.list_models()
        return True

    async def close(self) -> None:
        try:
            await self._client.aio.aclose()
        except Exception:  # pragma: no cover - best-effort cleanup
            logger.debug("gemini client close raised", exc_info=True)

    def _raise_translated(self, e: BaseException) -> None:
        msg = str(e)
        lowered = msg.lower()
        if (
            getattr(e, "code", None) in (401, 403)
            or "api key" in lowered
            or "unauthenticated" in lowered
            or "permission" in lowered
            or "invalid authentication" in lowered
        ):
            raise ProviderAuthError(msg, self.provider_name) from e
        raise ProviderError(msg, provider=self.provider_name) from e
