"""
The google-generativeai fallback of the Gemini provider, and the SDK choice.

TODO(env-upgrade): delete with LegacyGeminiProvider once production has
google-genai. The legacy SDK is replaced by a fake module, so these tests run
whether or not either Gemini SDK is installed.
"""
import asyncio
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from advandeb_kb.services.llm_providers import gemini_provider as gp
from advandeb_kb.services.llm_providers.base import ProviderAuthError, ProviderError


class _FakeLegacySDK:
    """The slice of google.generativeai the provider uses, process-global like the real one."""

    def __init__(self, delay=0.0):
        self.configured_key = None
        self.delay = delay
        self.calls = []
        self.error = None
        sdk = self

        class GenerativeModel:
            def __init__(self, model_name, system_instruction=None):
                self.model_name = model_name
                self.system_instruction = system_instruction

            def generate_content(self, contents, generation_config=None, stream=False):
                # The key in effect when the request is made is the one it uses.
                key = sdk.configured_key
                time.sleep(sdk.delay)
                sdk.calls.append({"key": key, "model": self.model_name, "contents": contents,
                                  "config": generation_config, "system": self.system_instruction})
                if sdk.error:
                    raise sdk.error
                if stream:
                    return iter([_resp("Ener"), _resp(""), _resp("gy")])
                return _resp(f"answer for {key}")

        self.GenerativeModel = GenerativeModel

    def configure(self, api_key):
        self.configured_key = api_key

    def list_models(self):
        yield SimpleNamespace(name="models/gemini-2.5-flash", supported_generation_methods=["generateContent"])
        yield SimpleNamespace(name="models/embedding-001", supported_generation_methods=["embedContent"])


def _resp(text):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))],
        usage_metadata=SimpleNamespace(prompt_token_count=4, candidates_token_count=2, total_token_count=6),
    )


@pytest.fixture
def sdk(monkeypatch):
    fake = _FakeLegacySDK()
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)
    return fake


@pytest.mark.parametrize("available, expected", [
    ({"google.genai", "google.generativeai"}, "google-genai"),
    ({"google.genai"}, "google-genai"),
    ({"google.generativeai"}, "google-generativeai"),
    (set(), None),
])
def test_sdk_choice_prefers_google_genai(monkeypatch, available, expected):
    monkeypatch.setattr(gp.importlib.util, "find_spec",
                        lambda name: object() if name in available else None)
    assert gp._detect_sdk() == expected


def test_sdk_choice_survives_a_missing_google_package(monkeypatch):
    def find_spec(name):
        raise ModuleNotFoundError("No module named 'google'")
    monkeypatch.setattr(gp.importlib.util, "find_spec", find_spec)
    assert gp._detect_sdk() is None


def test_registry_class_follows_the_choice():
    assert gp._provider_class("google-generativeai") is gp.LegacyGeminiProvider
    assert gp._provider_class("google-genai") is gp.GenAIGeminiProvider
    assert gp._provider_class(None) is gp.GenAIGeminiProvider
    assert gp.GeminiProvider is gp._provider_class(gp._SDK)


def test_without_any_sdk_the_error_is_a_provider_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "google.genai", None)  # import raises ImportError
    with pytest.raises(ProviderError, match="google-genai"):
        gp.GenAIGeminiProvider(api_key="k")


def test_missing_key_is_an_auth_error(sdk):
    with pytest.raises(ProviderAuthError):
        gp.LegacyGeminiProvider(api_key="")


async def test_completion_uses_this_providers_key(sdk):
    p = gp.LegacyGeminiProvider(api_key="key-a")
    out = await p.chat_completion(
        "gemini-2.5-flash",
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}],
        temperature=0.1, max_tokens=32,
    )
    call = sdk.calls[0]
    assert call["key"] == "key-a"
    assert call["system"] == "Be brief."
    assert call["config"] == {"temperature": 0.1, "max_output_tokens": 32}
    assert out["choices"][0]["message"]["content"] == "answer for key-a"
    assert out["usage"] == {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}


async def test_stream_yields_deltas_then_stop(sdk):
    p = gp.LegacyGeminiProvider(api_key="k")
    stream = await p.chat_completion("gemini-2.5-flash", [{"role": "user", "content": "x"}], stream=True)
    chunks = [c async for c in stream]
    assert [c["choices"][0]["delta"].get("content") for c in chunks] == ["Ener", "gy", None]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


async def test_list_models_and_validate(sdk):
    p = gp.LegacyGeminiProvider(api_key="k")
    assert await p.list_models() == ["gemini-2.5-flash"]
    assert await p.validate() is True


async def test_invalid_key_becomes_auth_error(sdk):
    sdk.error = RuntimeError("400 API key not valid. Please pass a valid API key.")
    p = gp.LegacyGeminiProvider(api_key="bad")
    with pytest.raises(ProviderAuthError):
        await p.chat_completion("gemini-2.5-flash", [{"role": "user", "content": "x"}])


async def test_concurrent_users_never_get_each_others_key(monkeypatch):
    """The SDK's key is process-wide; the lock keeps configure + request together."""
    fake = _FakeLegacySDK(delay=0.005)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)
    providers = [gp.LegacyGeminiProvider(api_key=f"key-{i}") for i in range(4)]

    results = await asyncio.gather(*[
        p.chat_completion("gemini-2.5-flash", [{"role": "user", "content": "x"}])
        for p in providers for _ in range(5)
    ])

    answers = [r["choices"][0]["message"]["content"] for r in results]
    assert answers == [f"answer for key-{i}" for i in range(4) for _ in range(5)]
    assert all(call["key"] is not None for call in fake.calls)
    assert isinstance(gp._LEGACY_KEY_LOCK, type(threading.Lock()))
