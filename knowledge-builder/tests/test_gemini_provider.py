"""
GeminiProvider on the google-genai SDK.

The client is a fake (no network, no key), but requests and responses use the
SDK's own types, so the translation helpers are checked against the real
response shape rather than a hand-made stand-in.
"""
import pytest

genai = pytest.importorskip("google.genai")
from google.genai import errors, types  # noqa: E402

from advandeb_kb.services.llm_providers import gemini_provider  # noqa: E402
from advandeb_kb.services.llm_providers.base import (  # noqa: E402
    ProviderAuthError,
    ProviderError,
)
from advandeb_kb.services.llm_providers.gemini_provider import GeminiProvider  # noqa: E402


async def _aiter(items):
    for item in items:
        yield item


class _FakeModels:
    def __init__(self):
        self.calls = []
        self.response = None
        self.chunks = []
        self.models = []
        self.error = None

    async def generate_content(self, *, model, contents, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return self.response

    async def generate_content_stream(self, *, model, contents, config=None):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return _aiter(self.chunks)

    async def list(self, *, config=None):
        if self.error:
            raise self.error
        return _aiter(self.models)


class _FakeAio:
    def __init__(self):
        self.models = _FakeModels()
        self.closed = False

    async def aclose(self):
        self.closed = True


class _FakeClient:
    def __init__(self, *, api_key):
        self.api_key = api_key
        self.aio = _FakeAio()


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch):
    monkeypatch.setattr(genai, "Client", _FakeClient)


def _response(text, finish=types.FinishReason.STOP):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)]),
                finish_reason=finish,
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=7, candidates_token_count=3, total_token_count=10
        ),
    )


def test_each_provider_keeps_its_own_key():
    """Keys are per client, not process-wide as with genai.configure()."""
    a = GeminiProvider(api_key="key-a")
    b = GeminiProvider(api_key="key-b")
    assert (a._client.api_key, b._client.api_key) == ("key-a", "key-b")


def test_missing_key_is_an_auth_error():
    with pytest.raises(ProviderAuthError):
        GeminiProvider(api_key="")


async def test_chat_completion_request_and_response():
    p = GeminiProvider(api_key="k")
    p._client.aio.models.response = _response("Energy is conserved.")

    out = await p.chat_completion(
        "gemini-2.5-flash",
        [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "What is DEB?"},
        ],
        temperature=0.2,
        max_tokens=64,
    )

    call = p._client.aio.models.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert [m["role"] for m in call["contents"]] == ["user", "model", "user"]
    assert call["config"].system_instruction == "Be brief."
    assert call["config"].temperature == 0.2
    assert call["config"].max_output_tokens == 64

    assert out["choices"][0]["message"] == {"role": "assistant", "content": "Energy is conserved."}
    assert out["choices"][0]["finish_reason"] == "stop"
    assert out["usage"] == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}


async def test_stream_yields_text_deltas_then_stop():
    p = GeminiProvider(api_key="k")
    p._client.aio.models.chunks = [_response("Ener"), _response(""), _response("gy")]

    stream = await p.chat_completion("gemini-2.5-flash", [{"role": "user", "content": "x"}], stream=True)
    chunks = [c async for c in stream]

    assert [c["choices"][0]["delta"].get("content") for c in chunks] == ["Ener", "gy", None]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


async def test_list_models_keeps_generate_content_models_without_prefix():
    p = GeminiProvider(api_key="k")
    p._client.aio.models.models = [
        types.Model(name="models/gemini-2.5-flash", supported_actions=["generateContent", "countTokens"]),
        types.Model(name="models/text-embedding-004", supported_actions=["embedContent"]),
        types.Model(name="models/gemini-2.5-pro", supported_actions=["generateContent"]),
    ]
    assert await p.list_models() == ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert await p.validate() is True


async def test_invalid_key_becomes_provider_auth_error():
    p = GeminiProvider(api_key="bad")
    p._client.aio.models.error = errors.ClientError(
        400,
        {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                   "status": "INVALID_ARGUMENT"}},
    )
    with pytest.raises(ProviderAuthError):
        await p.validate()


async def test_server_error_is_a_plain_provider_error():
    p = GeminiProvider(api_key="k")
    p._client.aio.models.error = errors.ServerError(
        503, {"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}}
    )
    with pytest.raises(ProviderError) as exc:
        await p.chat_completion("gemini-2.5-flash", [{"role": "user", "content": "x"}])
    assert not isinstance(exc.value, ProviderAuthError)


async def test_close_closes_the_async_client():
    p = GeminiProvider(api_key="k")
    await p.close()
    assert p._client.aio.closed


def test_finish_reason_is_lowercased_enum_name():
    assert gemini_provider._finish_reason(_response("x", types.FinishReason.MAX_TOKENS)) == "max_tokens"
