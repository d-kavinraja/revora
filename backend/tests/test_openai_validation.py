"""OpenAI provider validation tests."""

import datetime
from unittest.mock import patch

import pytest

from app.core.security import encryption_service
from app.services import model_discovery as md


def _md():
    md._MODEL_CACHE.clear()
    return md


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response, routes=None):
        self._response = response
        self._routes = routes or {}
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        url = args[0] if args else ""
        for fragment, routed in self._routes.items():
            if fragment in url:
                if isinstance(routed, Exception):
                    raise routed
                return routed
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


_FAKE_KEY = "sk-openai-test-fake-key-000000000000"


@pytest.mark.asyncio
async def test_openai_adapter_provider_slug():
    from app.ai.discovery.openai import OpenAIDiscoveryAdapter

    assert OpenAIDiscoveryAdapter().provider_slug == "openai"


@pytest.mark.asyncio
async def test_openai_models_200_returns_chat_models():
    mdmod = _md()
    catalogue = [
        {"id": "gpt-4o"},
        {"id": "gpt-4o-mini"},
        {"id": "text-embedding-3-small"},  # filtered
    ]
    routes = {"api.openai.com": _FakeResponse(200, {"data": catalogue})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            mdmod.litellm,
            "get_valid_models",
            side_effect=AssertionError("openai must not call litellm.get_valid_models"),
        ),
        patch.object(mdmod.litellm, "completion", return_value={"choices": []}),
    ):
        models = await mdmod.model_discovery_engine.get_available_models(
            "openai", _FAKE_KEY, force_refresh=True
        )
    assert len(models) == 2
    names = {m["canonical_model_name"] for m in models}
    assert "gpt-4o" in names
    assert "gpt-4o-mini" in names
    assert "text-embedding-3-small" not in names


@pytest.mark.asyncio
async def test_openai_models_401_maps_to_auth_error():
    from app.services.model_discovery import ProviderAuthError

    mdmod = _md()
    routes = {"api.openai.com": _FakeResponse(401, {"error": {"code": 401}})}
    fake = _FakeAsyncClient(None, routes=routes)
    with patch("httpx.AsyncClient", return_value=fake), pytest.raises(ProviderAuthError) as exc:
        await mdmod.model_discovery_engine.get_available_models(
            "openai", "bad-key", force_refresh=True
        )
    assert exc.value.error_type == "invalid_key"


@pytest.mark.asyncio
async def test_openai_models_403_maps_to_authorization_error():
    from app.services.model_discovery import ProviderAuthError

    mdmod = _md()
    routes = {"api.openai.com": _FakeResponse(403, {"error": {"code": 403}})}
    fake = _FakeAsyncClient(None, routes=routes)
    with patch("httpx.AsyncClient", return_value=fake), pytest.raises(ProviderAuthError) as exc:
        await mdmod.model_discovery_engine.get_available_models(
            "openai", "bad-key", force_refresh=True
        )
    assert exc.value.error_type == "authorization_error"


@pytest.mark.asyncio
async def test_openai_models_429_maps_to_busy():
    from app.services.model_discovery import ProviderBusyError

    mdmod = _md()
    routes = {"api.openai.com": _FakeResponse(429, {})}
    fake = _FakeAsyncClient(None, routes=routes)
    with patch("httpx.AsyncClient", return_value=fake), pytest.raises(ProviderBusyError):
        await mdmod.model_discovery_engine.get_available_models(
            "openai", _FAKE_KEY, force_refresh=True
        )


@pytest.mark.asyncio
async def test_openai_models_transport_failure_is_busy():
    from app.services.model_discovery import ProviderBusyError

    mdmod = _md()
    routes = {"api.openai.com": ConnectionError("connection reset")}
    fake = _FakeAsyncClient(None, routes=routes)
    with patch("httpx.AsyncClient", return_value=fake), pytest.raises(ProviderBusyError):
        await mdmod.model_discovery_engine.get_available_models(
            "openai", _FAKE_KEY, force_refresh=True
        )


@pytest.mark.asyncio
async def test_openai_models_empty_catalogue_is_unavailable():
    from app.services.model_discovery import ProviderUnavailableError

    mdmod = _md()
    routes = {"api.openai.com": _FakeResponse(200, {"data": []})}
    fake = _FakeAsyncClient(None, routes=routes)
    with patch("httpx.AsyncClient", return_value=fake), pytest.raises(ProviderUnavailableError) as exc:
        await mdmod.model_discovery_engine.get_available_models(
            "openai", _FAKE_KEY, force_refresh=True
        )
    assert exc.value.error_type == "provider_unavailable"


@pytest.mark.asyncio
async def test_openai_resolve_model_prefix():
    from app.ai.llm import llm_service

    # OpenAI canonical may or may not be registered; fallback should not crash.
    name, _ = llm_service._resolve_model("openai", "gpt-4o")
    assert "gpt-4o" in name


def test_openai_cost_rates():
    from app.services.cost_estimator import cost_estimator

    rates = cost_estimator.get_rates("openai")
    assert rates["input"] > 0
    assert rates["output"] > 0