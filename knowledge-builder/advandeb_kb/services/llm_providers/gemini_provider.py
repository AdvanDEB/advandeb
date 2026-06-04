"""
Google Gemini provider (BYOK).

Gemini's chat API differs from OpenAI's in three ways that this adapter has
to bridge:

1. Messages use ``parts=[{"text": ...}]`` instead of a flat ``content`` string.
2. The assistant role is named ``model`` (we map ``assistant`` <-> ``model``).
3. System prompts are passed once via ``system_instruction`` on the model,
   not as a message in the conversation.

Responses are translated back into the OpenAI-compatible shape used
throughout the codebase.
"""
from __future__ import annotations

import asyncio
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
    """Gemini chat provider using the ``google-generativeai`` SDK."""

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
        import google.generativeai as genai  # type: ignore

        self._genai = genai
        self._api_key = api_key
        # ``genai.configure`` is process-global; setting it here is fine for
        # the common BYOK case where one key is active per request.
        genai.configure(api_key=api_key)

    def _build_model(self, model: str, system_instruction: Optional[str]) -> Any:
        kwargs: Dict[str, Any] = {"model_name": model}
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        return self._genai.GenerativeModel(**kwargs)

    def _generation_config(
        self, temperature: float, max_tokens: Optional[int]
    ) -> Dict[str, Any]:
        cfg: Dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            cfg["max_output_tokens"] = max_tokens
        return cfg

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
        gen_config = self._generation_config(temperature, max_tokens)
        gen_model = self._build_model(model, system)

        if stream:
            return self._stream(gen_model, gemini_msgs, gen_config, model)

        try:
            # The SDK's ``generate_content`` is blocking; run in a worker
            # thread to keep our public API async.
            response = await asyncio.to_thread(
                gen_model.generate_content,
                gemini_msgs,
                generation_config=gen_config,
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
        gen_model: Any,
        gemini_msgs: List[Dict[str, Any]],
        gen_config: Dict[str, Any],
        model_name: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        # ``generate_content(stream=True)`` returns a synchronous iterator of
        # partial ``GenerateContentResponse``s. Pull each chunk on a worker
        # thread to avoid blocking the event loop.
        try:
            iterator = await asyncio.to_thread(
                gen_model.generate_content,
                gemini_msgs,
                generation_config=gen_config,
                stream=True,
            )
        except Exception as e:
            self._raise_translated(e)
            return  # pragma: no cover - _raise_translated always raises

        sentinel = object()

        def _next_chunk():
            try:
                return next(iterator)
            except StopIteration:
                return sentinel

        try:
            while True:
                chunk = await asyncio.to_thread(_next_chunk)
                if chunk is sentinel:
                    break
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

        ``genai.list_models()`` is a blocking, authenticated call — run it on a
        worker thread. Model names come back as ``models/<id>``; strip the
        prefix to match what callers pass to ``generate_content``.
        """

        def _list() -> List[str]:
            out: List[str] = []
            for m in self._genai.list_models():
                methods = getattr(m, "supported_generation_methods", []) or []
                if "generateContent" not in methods:
                    continue
                name = getattr(m, "name", "") or ""
                out.append(name[len("models/"):] if name.startswith("models/") else name)
            return out

        try:
            return await asyncio.to_thread(_list)
        except Exception as e:
            self._raise_translated(e)
            return []  # pragma: no cover - _raise_translated always raises

    async def validate(self) -> bool:
        # A successful authenticated list call proves the key works without
        # depending on any particular (possibly retired) model name.
        await self.list_models()
        return True

    async def close(self) -> None:
        # google-generativeai uses a process-global session; nothing to close.
        return None

    def _raise_translated(self, e: BaseException) -> None:
        msg = str(e)
        lowered = msg.lower()
        if (
            "api key" in lowered
            or "unauthenticated" in lowered
            or "permission" in lowered
            or "invalid authentication" in lowered
        ):
            raise ProviderAuthError(msg, self.provider_name) from e
        raise ProviderError(msg, provider=self.provider_name) from e
