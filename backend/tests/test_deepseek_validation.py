"""DeepSeek provider validation tests."""

from unittest.mock import patch

import pytest

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


_FAKE_KEY = "sk-deepseek-test-fake-key-000000000000"


@pytest.mark.asyncio
async def test_deepseek_adapter_provider_slug():
    from app.ai.discovery.deepseek import DeepSeekDiscoveryAdapter

    assert DeepSeekDiscoveryAdapter().provider_slug == "deepseek"


@pytest.mark.asyncio
async def test_deepseek_models_200_returns_chat_models():
    mdmod = _md()
    catalogue = [
        {"id": "deepseek-chat"},
        {"id": "deepseek-reasoner"},
    ]
    routes = {"api.deepseek.com": _FakeResponse(200, {"data": catalogue})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            mdmod.litellm,
            "get_valid_models",
            side_effect=AssertionError("deepseek must not call litellm.get_valid_models"),
        ),
        patch.object(mdmod.litellm, "completion", return_value={"choices": []}),
    ):
        models = await mdmod.model_discovery_engine.get_available_models(
            "deepseek", _FAKE_KEY, force_refresh=True
        )
    assert len(models) == 2
    names = {m["canonical_model_name"] for m in models}
    assert "deepseek-chat" in names
    assert "deepseek-reasoner" in names
    assert all(m["litellm_model_name"].startswith("deepseek/") for m in models)


@pytest.mark.asyncio
async def test_deepseek_models_401_maps_to_auth_error():
    from app.services.model_discovery import ProviderAuthError

    mdmod = _md()
    routes = {"api.deepseek.com": _FakeResponse(401, {"error": {"code": 401}})}
    fake = _FakeAsyncClient(None, routes=routes)
    with patch("httpx.AsyncClient", return_value=fake), pytest.raises(ProviderAuthError) as exc:
        await mdmod.model_discovery_engine.get_available_models(
            "deepseek", "bad-key", force_refresh=True
        )
    assert exc.value.error_type == "invalid_key"


@pytest.mark.asyncio
async def test_deepseek_models_403_maps_to_authorization_error():
    from app.services.model_discovery import ProviderAuthError

    mdmod = _md()
    routes = {"api.deepseek.com": _FakeResponse(403, {"error": {"code": 403}})}
    fake = _FakeAsyncClient(None, routes=routes)
    with patch("httpx.AsyncClient", return_value=fake), pytest.raises(ProviderAuthError) as exc:
        await mdmod.model_discovery_engine.get_available_models(
            "deepseek", "bad-key", force_refresh=True
        )
    assert exc.value.error_type == "authorization_error"


@pytest.mark.asyncio
async def test_deepseek_models_429_maps_to_busy():
    from app.services.model_discovery import ProviderBusyError

    mdmod = _md()
    routes = {"api.deepseek.com": _FakeResponse(429, {})}
    fake = _FakeAsyncClient(None, routes=routes)
    with patch("httpx.AsyncClient", return_value=fake), pytest.raises(ProviderBusyError):
        await mdmod.model_discovery_engine.get_available_models(
            "deepseek", _FAKE_KEY, force_refresh=True
        )


@pytest.mark.asyncio
async def test_deepseek_models_transport_failure_is_busy():
    from app.services.model_discovery import ProviderBusyError

    mdmod = _md()
    routes = {"api.deepseek.com": ConnectionError("connection reset")}
    fake = _FakeAsyncClient(None, routes=routes)
    with patch("httpx.AsyncClient", return_value=fake), pytest.raises(ProviderBusyError):
        await mdmod.model_discovery_engine.get_available_models(
            "deepseek", _FAKE_KEY, force_refresh=True
        )


@pytest.mark.asyncio
async def test_deepseek_models_empty_catalogue_is_unavailable():
    from app.services.model_discovery import ProviderUnavailableError

    mdmod = _md()
    routes = {"api.deepseek.com": _FakeResponse(200, {"data": []})}
    fake = _FakeAsyncClient(None, routes=routes)
    with patch("httpx.AsyncClient", return_value=fake), pytest.raises(ProviderUnavailableError) as exc:
        await mdmod.model_discovery_engine.get_available_models(
            "deepseek", _FAKE_KEY, force_refresh=True
        )
    assert exc.value.error_type == "provider_unavailable"


@pytest.mark.asyncio
async def test_deepseek_resolve_model_prefix():
    from app.ai.llm import llm_service

    name, _ = llm_service._resolve_model("deepseek", "deepseek-chat")
    assert name == "deepseek/deepseek-chat"


def test_deepseek_cost_rates():
    from app.services.cost_estimator import cost_estimator

    rates = cost_estimator.get_rates("deepseek")
    assert rates["input"] > 0
    assert rates["output"] > 0