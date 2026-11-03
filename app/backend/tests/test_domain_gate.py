"""
Unit tests for the domain-relevance gate (``app.kb.pipeline._classify_domain_relevance``).

The Ollama call is patched via ``httpx.AsyncClient.post`` so no model is needed.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.kb.pipeline import DOMAIN_GATE_FAILED_REASON, _classify_domain_relevance


def _ollama_reply(content: str) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"message": {"content": content}})
    return resp


async def _gate(content: str, **kwargs):
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_ollama_reply(content))) as post:
        result = await _classify_domain_relevance("Title", "Some abstract text.", **kwargs)
    return result, post


@pytest.mark.parametrize(
    "content, expected",
    [
        (json.dumps({"relevant": True, "reason": "fish growth"}), True),
        (json.dumps({"relevant": False, "reason": "android security"}), False),
        # Quoted booleans: bool("false") would wrongly read as relevant.
        (json.dumps({"relevant": "false", "reason": "R0 epidemiology"}), False),
        (json.dumps({"relevant": "true", "reason": "oocyte maturation"}), True),
        ('```json\n{"relevant": false, "reason": "brand value"}\n```', False),
        ('<think>hmm</think>{"relevant": false, "reason": "theology"}', False),
    ],
)
async def test_verdict_parsing(content, expected):
    (is_relevant, reason), _ = await _gate(content)
    assert is_relevant is expected
    assert reason


async def test_unparseable_reply_fails_open_with_marker_reason():
    (is_relevant, reason), _ = await _gate("I think this paper is about software.")
    assert is_relevant is True
    assert reason == DOMAIN_GATE_FAILED_REASON


async def test_missing_abstract_skips_the_model():
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as post:
        is_relevant, _ = await _classify_domain_relevance("Title", "  ")
    assert is_relevant is True
    post.assert_not_called()


async def test_base_url_override_is_used():
    _, post = await _gate(json.dumps({"relevant": True, "reason": "ok"}),
                          base_url="http://gpu3:11434")
    assert post.call_args.args[0] == "http://gpu3:11434/api/chat"
