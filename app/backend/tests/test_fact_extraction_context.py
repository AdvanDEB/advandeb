"""Fact extraction must ask Ollama for a context window its sections fit in.

Without num_ctx, Ollama loaded deepseek-r1 with a 2048-token slot (4096 split
over OLLAMA_NUM_PARALLEL=2) and silently dropped most of every 80k-character
section it was sent.
"""

import httpx
import pytest

from advandeb_kb.config.settings import settings
from app.kb import pipeline


class _Response:
    def __init__(self, prompt_tokens):
        self._prompt_tokens = prompt_tokens

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": '["Reserve density scales with structural volume."]'},
                "prompt_eval_count": self._prompt_tokens}


class _Client:
    sent: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        _Client.sent.append(json)
        return _Response(prompt_tokens=len(json["messages"][1]["content"]) // 4)


@pytest.fixture
def ollama(monkeypatch):
    _Client.sent = []
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return _Client


@pytest.mark.asyncio
async def test_every_request_sets_num_ctx_and_sections_fit(ollama):
    text = "The kappa rule allocates a fixed fraction to soma. " * 4000   # ~200k chars
    facts = await pipeline._extract_facts(text)

    num_ctx = settings.FACT_EXTRACTION_NUM_CTX
    num_predict = settings.FACT_EXTRACTION_NUM_PREDICT
    section_chars = (num_ctx - num_predict - 1024) * 3
    assert facts == ["Reserve density scales with structural volume."]
    assert len(ollama.sent) >= len(text) // section_chars
    for payload in ollama.sent:
        assert payload["options"]["num_ctx"] == num_ctx
        assert payload["options"]["num_predict"] == num_predict
        section = payload["messages"][1]["content"].split("\n\n", 1)[1]
        assert len(section) <= section_chars


@pytest.mark.asyncio
async def test_the_whole_text_is_sent(ollama):
    text = "".join(f"sentence {i:05d}. " for i in range(12000))
    await pipeline._extract_facts(text)
    sent = "".join(p["messages"][1]["content"].split("\n\n", 1)[1] for p in ollama.sent)
    for i in (0, 6000, 11999):
        assert f"sentence {i:05d}." in sent
