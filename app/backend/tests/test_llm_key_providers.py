"""
Regression tests for the BYOK provider allow-list.

The bug these guard against: the ``GET /providers`` route advertised a provider
("nvidia") that ``create_key`` did not accept, so the UI happily offered NVIDIA
NIM in its picker and every attempt to save such a key was rejected with
``422 Unknown provider: 'nvidia'``. Users on the shared default key had no way
to add their own credentials.

The invariant is now structural — both sides read ``BYOK_PROVIDER_NAMES`` — but
these tests fail loudly if anyone reintroduces a second, divergent list.
"""
import pytest

from advandeb_kb.services.llm_providers import PROVIDERS, list_providers
from app.services.llm_key_service import BYOK_PROVIDER_NAMES


def test_nvidia_is_accepted_by_the_allow_list():
    """The specific provider that regressed."""
    assert "nvidia" in BYOK_PROVIDER_NAMES


def test_ollama_is_never_byok():
    """Ollama is local and has no key to store — it must stay excluded."""
    assert "ollama" not in BYOK_PROVIDER_NAMES


def test_every_allowed_provider_is_constructible():
    """A provider we accept keys for must exist in the KB registry.

    Otherwise create_key() passes its own allow-list and then trips the second
    ``provider not in PROVIDERS`` check with the same opaque 422.
    """
    missing = BYOK_PROVIDER_NAMES - set(PROVIDERS)
    assert not missing, f"allow-listed but not in the provider registry: {missing}"


def test_advertised_providers_are_all_acceptable():
    """Everything the picker offers must be storable.

    This is the exact invariant that broke: catalog ⊇ allow-list is fine, but
    anything *advertised* and not *accepted* is a guaranteed 422 for the user.
    """
    advertised = {
        p["name"] for p in list_providers() if p["name"] in BYOK_PROVIDER_NAMES
    }
    assert advertised <= BYOK_PROVIDER_NAMES

    # And the route must not filter through a hand-maintained copy of the set.
    import inspect

    from app.api.routes import llm_keys

    source = inspect.getsource(llm_keys.list_supported_providers)
    assert "BYOK_PROVIDER_NAMES" in source, (
        "the /providers route must filter through the shared allow-list, "
        "not an inline set that can drift"
    )


def test_create_key_validates_explicitly():
    """create_key must call validate(), not infer it from list_models().

    NVIDIA NIM serves GET /v1/models with no Authorization header at all, so a
    catalog fetch succeeds for any string. Relying on it meant junk NVIDIA keys
    were stored and reported to the user as "validated and saved", then failed
    later at chat time.
    """
    import inspect

    from app.services.llm_key_service import LLMKeyService

    source = inspect.getsource(LLMKeyService.create_key)
    assert ".validate()" in source, (
        "create_key must call provider.validate() — list_models() succeeding "
        "does not prove the key authenticates on every provider"
    )


def test_nvidia_overrides_validate():
    """NVIDIA must not inherit the base 'a list call proves the key' logic."""
    from advandeb_kb.services.llm_providers.nvidia_provider import NvidiaProvider
    from advandeb_kb.services.llm_providers.openai_provider import OpenAIProvider

    assert NvidiaProvider.validate is not OpenAIProvider.validate, (
        "NvidiaProvider.validate must be overridden — /v1/models is "
        "unauthenticated on NIM, so the inherited check accepts any key"
    )


@pytest.mark.parametrize("provider", sorted(BYOK_PROVIDER_NAMES))
def test_allow_list_entries_are_key_bearing(provider):
    """Each allow-listed provider should accept an api_key at construction."""
    cls = PROVIDERS[provider]
    sig = __import__("inspect").signature(cls.__init__)
    assert "api_key" in sig.parameters, f"{provider} takes no api_key"


# ── NVIDIA key check: only 401/403 means a bad key ──────────────────────────
#
# NIM checks the model before the key: a retired model answers 410 and an
# unknown one 404 whatever the key. validate() used to ping one fixed model, so
# a good key was reported as failing whenever that model was retired, degraded
# or out of reach for the account.

import asyncio

from advandeb_kb.services.llm_providers.base import ProviderAuthError, ProviderError


def _nvidia(catalog, answers):
    """An NvidiaProvider whose catalog and per-model completions are scripted.

    ``answers`` maps a model to the status code it fails with; any other model
    answers. Returns the provider and the list of models tried, in order.
    """
    from advandeb_kb.services.llm_providers.nvidia_provider import NvidiaProvider

    prov = NvidiaProvider(api_key="nvapi-test-0000")
    tried = []

    async def list_models():
        return list(catalog)

    async def chat_completion(model, messages, **kw):
        tried.append(model)
        code = answers.get(model)
        if code:
            raise ProviderError(f"Error code: {code}", provider="nvidia", code=str(code))
        return {"content": ""}

    prov.list_models = list_models
    prov.chat_completion = chat_completion
    return prov, tried


def test_nvidia_key_check_moves_past_an_unreachable_default():
    from advandeb_kb.services.llm_providers.nvidia_provider import NvidiaProvider

    default = NvidiaProvider.default_model
    fallback = NvidiaProvider.validation_fallbacks[0]
    prov, tried = _nvidia([default, fallback], {default: 404})

    assert asyncio.run(prov.validate()) is True
    assert tried == [default, fallback]
    assert prov.validated_model == fallback


def test_nvidia_key_check_stops_at_a_rejected_key():
    from advandeb_kb.services.llm_providers.nvidia_provider import NvidiaProvider

    default = NvidiaProvider.default_model
    prov, tried = _nvidia([default, *NvidiaProvider.validation_fallbacks], {default: 403})

    with pytest.raises(ProviderAuthError):
        asyncio.run(prov.validate())
    assert tried == [default]


def test_nvidia_key_check_skips_models_the_catalog_no_longer_lists():
    from advandeb_kb.services.llm_providers.nvidia_provider import NvidiaProvider

    live = NvidiaProvider.validation_fallbacks[-1]
    prov, tried = _nvidia([live], {})

    assert asyncio.run(prov.validate()) is True
    assert tried == [live]


def test_nvidia_key_check_reports_when_no_model_answers():
    from advandeb_kb.services.llm_providers.nvidia_provider import NvidiaProvider

    models = [NvidiaProvider.default_model, *NvidiaProvider.validation_fallbacks]
    prov, _ = _nvidia(models, {m: 503 for m in models})

    with pytest.raises(ProviderError) as info:
        asyncio.run(prov.validate())
    assert not isinstance(info.value, ProviderAuthError)
    assert prov.validated_model is None


def test_stored_default_is_the_model_the_key_reached():
    from types import SimpleNamespace

    from app.services.llm_key_service import _pick_default_model

    prov = SimpleNamespace(default_model="big", validated_model="small")
    assert _pick_default_model(prov, ["big", "small"], None) == "small"
    # An explicit, offered choice still wins.
    assert _pick_default_model(prov, ["big", "small"], "big") == "big"
