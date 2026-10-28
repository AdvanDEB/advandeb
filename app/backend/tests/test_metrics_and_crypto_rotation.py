"""/metrics instrumentation, chat-turn outcomes, and Fernet key rotation."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from app.core import config
from app.core import metrics as app_metrics
from app.core.database import redact_uri

prometheus_client = pytest.importorskip("prometheus_client")


def _sample(name: str, **labels) -> float:
    value = prometheus_client.REGISTRY.get_sample_value(name, labels)
    return value or 0.0


def _client(app, raise_app_exceptions=True) -> httpx.AsyncClient:
    # starlette 0.27's TestClient does not work with the installed httpx.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    return httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8400")


@pytest.fixture
def app():
    app = FastAPI()

    @app.get("/api/items/{item_id}")
    async def item(item_id: int):
        return {"id": item_id}

    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("boom")

    app.add_api_route("/metrics", app_metrics.metrics_endpoint, methods=["GET"])
    app.add_middleware(app_metrics.PrometheusMiddleware)
    return app


async def test_requests_are_labelled_by_route_template(app):
    before = _sample("advandeb_http_requests_total", method="GET", route="/api/items/{item_id}", status="200")
    async with _client(app) as client:
        for i in range(3):
            assert (await client.get(f"/api/items/{i}")).status_code == 200
    after = _sample("advandeb_http_requests_total", method="GET", route="/api/items/{item_id}", status="200")
    assert after - before == 3


async def test_unhandled_exception_counts_as_500(app):
    before = _sample("advandeb_http_requests_total", method="GET", route="/api/boom", status="500")
    async with _client(app, raise_app_exceptions=False) as client:
        assert (await client.get("/api/boom")).status_code == 500
    assert _sample("advandeb_http_requests_total", method="GET", route="/api/boom", status="500") - before == 1


async def test_metrics_endpoint_refuses_proxied_requests(app):
    async def no_probes():
        return None

    with patch.object(app_metrics, "refresh_dependencies", no_probes):
        async with _client(app) as client:
            direct = await client.get("/metrics")
            assert direct.status_code == 200
            assert "advandeb_http_requests_total" in direct.text
            proxied = await client.get("/metrics", headers={"X-Forwarded-For": "203.0.113.9"})
            assert proxied.status_code == 404
            tunnelled = await client.get("/metrics", headers={"CF-Connecting-IP": "203.0.113.9"})
            assert tunnelled.status_code == 404


@pytest.mark.parametrize(
    "events, default, expected",
    [
        ([{"type": "token"}, {"type": "message"}], "incomplete", "ok"),
        ([{"type": "error", "detail": "503 from provider"}], "incomplete", "error"),
        ([{"type": "token"}], "aborted", "aborted"),
        ([], "incomplete", "incomplete"),
    ],
)
def test_chat_turn_outcome(events, default, expected):
    before = _sample("advandeb_chat_turns_total", path="default", outcome=expected)
    turn = app_metrics.ChatTurnMetrics()
    turn.path = "default"
    for event in events:
        turn.see(event)
    turn.finish(default)
    assert _sample("advandeb_chat_turns_total", path="default", outcome=expected) - before == 1


def test_rate_limited_turn_keeps_its_outcome():
    before = _sample("advandeb_chat_turns_total", path="default", outcome="rate_limited")
    turn = app_metrics.ChatTurnMetrics()
    turn.path, turn.outcome = "default", "rate_limited"
    turn.see({"type": "error", "detail": "rate limited"})
    turn.finish("incomplete")
    assert _sample("advandeb_chat_turns_total", path="default", outcome="rate_limited") - before == 1


def test_redact_uri():
    assert redact_uri("mongodb://app:s3cr%40t@localhost:27017/?authSource=admin") == (
        "mongodb://app:***@localhost:27017/?authSource=admin"
    )
    assert redact_uri("mongodb://localhost:27017") == "mongodb://localhost:27017"


def test_crypto_decrypts_under_previous_key_and_encrypts_under_primary():
    from app.core import crypto

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    with patch.object(config.settings, "LLM_KEY_ENCRYPTION_KEY", old), \
         patch.object(config.settings, "LLM_KEY_ENCRYPTION_KEY_PREVIOUS", None):
        legacy = crypto.encrypt("sk-user-key")

    with patch.object(config.settings, "LLM_KEY_ENCRYPTION_KEY", new), \
         patch.object(config.settings, "LLM_KEY_ENCRYPTION_KEY_PREVIOUS", old):
        assert crypto.decrypt(legacy) == "sk-user-key"
        fresh = crypto.encrypt("sk-user-key")
    assert Fernet(new.encode()).decrypt(fresh.encode()) == b"sk-user-key"

    with patch.object(config.settings, "LLM_KEY_ENCRYPTION_KEY", new), \
         patch.object(config.settings, "LLM_KEY_ENCRYPTION_KEY_PREVIOUS", None):
        with pytest.raises(crypto.CryptoError):
            crypto.decrypt(legacy)


def test_invalid_previous_key_error_does_not_echo_the_value():
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        config.Settings(LLM_KEY_ENCRYPTION_KEY_PREVIOUS="not-a-key-SECRETVALUE")
    assert "SECRETVALUE" not in str(exc.value)
