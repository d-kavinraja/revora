"""Mistral provider validation tests.

Covers:
  - MistralDiscoveryAdapter: model discovery, non-chat filtering,
    context-window defaults, metadata, display_name.
  - ModelDiscoveryEngine.get_available_models("mistral", ...):
    HTTP status code → error-class mapping, empty-catalogue handling,
    transport-error handling, and a guard that the Mistral path never
    delegates to ``litellm.get_valid_models``.
  - LLMService._resolve_model: ``mistral/`` prefix is prepended.
  - CostEstimator rates for ``mistral``.

All credentials below are fake/mocked. Never use a real key in tests.
"""

import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encryption_service
from app.models.api_key import ApiKey

_FAKE_MISTRAL_KEY = "mistra-test-fake-key-000000000000"


def _md():
    """Import and clear the Mistral-scoped model-discovery cache."""
    from app.services import model_discovery as md

    md._MODEL_CACHE.clear()
    return md


# ---------------------------------------------------------------------------
# Shared test doubles (mirroring the OpenRouter test pattern)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("GET", "https://api.mistral.ai/v1/models")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response
            )


class _FakeAsyncClient:
    """Fake httpx.AsyncClient capturing the request for assertions.

    Pass ``routes`` to serve different responses per URL substring
    (matched in insertion order); otherwise every GET returns
    ``response`` (or raises it, if it is an Exception).
    """

    def __init__(self, response, routes=None):
        self._response = response
        self._routes = routes or {}
        self.calls: list[dict] = []

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


async def _make_key(
    test_db, mock_user, provider="mistral", raw=_FAKE_MISTRAL_KEY, is_valid=True
):
    key = ApiKey(
        user_id=mock_user.id,
        provider=provider,
        label=f"Test {provider}",
        encrypted_key=encryption_service.encrypt(raw),
        is_valid=is_valid,
    )
    test_db.add(key)
    await test_db.commit()
    await test_db.refresh(key)
    return key


# ---------------------------------------------------------------------------
# 1. MistralDiscoveryAdapter
# ---------------------------------------------------------------------------


def test_mistral_adapter_provider_slug():
    """The adapter must report the correct provider slug."""
    from app.ai.discovery.mistral import MistralDiscoveryAdapter

    adapter = MistralDiscoveryAdapter()
    assert adapter.provider_slug == "mistral"


@pytest.mark.asyncio
async def test_mistral_discovery_adapter_filters_embed_models():
    """Non-chat models (embed, embedding, moderation) must be excluded."""
    from app.ai.discovery.mistral import MistralDiscoveryAdapter

    payload = {
        "data": [
            {
                "id": "mistral-large-latest",
                "name": "Mistral Large",
                "max_context": 128000,
            },
            {"id": "mistral-embed", "name": "Mistral Embed", "max_context": 8192},
            {
                "id": "mistral-embedding-v1",
                "name": "Mistral Embedding",
                "max_context": 8192,
            },
            {
                "id": "moderation-latest",
                "name": "Mistral Moderation",
                "max_context": 4096,
            },
        ]
    }
    adapter = MistralDiscoveryAdapter()
    fake_resp = _FakeResponse(200, payload)
    mock_client = _FakeAsyncClient(fake_resp)
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await adapter.fetch_models("fake-key")

    model_ids = [m.model_id for m in result]
    assert "mistral-large-latest" in model_ids
    assert "mistral-embed" not in model_ids
    assert "mistral-embedding-v1" not in model_ids
    assert "moderation-latest" not in model_ids


@pytest.mark.asyncio
async def test_mistral_discovery_adapter_returns_context_window():
    """Discovered models must carry the correct context_window from the API."""
    from app.ai.discovery.mistral import MistralDiscoveryAdapter

    payload = {
        "data": [
            {
                "id": "mistral-small-latest",
                "name": "Mistral Small",
                "max_context": 8192,
            },
            {
                "id": "mistral-large-latest",
                "name": "Mistral Large",
                "max_context": 128000,
            },
        ]
    }
    adapter = MistralDiscoveryAdapter()
    mock_client = _FakeAsyncClient(_FakeResponse(200, payload))
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await adapter.fetch_models("fake-key")

    by_id = {m.model_id: m for m in result}
    assert by_id["mistral-small-latest"].context_window == 8192
    assert by_id["mistral-large-latest"].context_window == 128000


@pytest.mark.asyncio
async def test_mistral_discovery_adapter_defaults_context_window():
    """When max_context is missing, the adapter must fall back to 128000."""
    from app.ai.discovery.mistral import (
        MistralDiscoveryAdapter,
        _DEFAULT_MISTRAL_CONTEXT,
    )

    payload = {
        "data": [
            {"id": "mistral-medium-latest", "name": "Mistral Medium"},
        ]
    }
    adapter = MistralDiscoveryAdapter()
    mock_client = _FakeAsyncClient(_FakeResponse(200, payload))
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await adapter.fetch_models("fake-key")

    assert result[0].context_window == _DEFAULT_MISTRAL_CONTEXT


@pytest.mark.asyncio
async def test_mistral_discovery_adapter_sets_display_name():
    """display_name must come from the API ``name`` field, falling back to model_id."""
    from app.ai.discovery.mistral import MistralDiscoveryAdapter

    payload = {
        "data": [
            {"id": "mistral-large-latest", "name": "Mistral Large"},
            {"id": "some-model", "name": ""},  # empty name → fallback to id
        ]
    }
    adapter = MistralDiscoveryAdapter()
    mock_client = _FakeAsyncClient(_FakeResponse(200, payload))
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await adapter.fetch_models("fake-key")

    by_id = {m.model_id: m for m in result}
    assert by_id["mistral-large-latest"].display_name == "Mistral Large"
    assert by_id["some-model"].display_name == "some-model"


@pytest.mark.asyncio
async def test_mistral_discovery_adapter_sets_metadata_and_description():
    """Discovered models must carry raw_metadata and a human-readable description."""
    from app.ai.discovery.mistral import MistralDiscoveryAdapter

    payload = {
        "data": [
            {
                "id": "mistral-large-latest",
                "name": "Mistral Large",
                "max_context": 128000,
                "capabilities": {"completion_chat": True, "streaming": True},
            },
        ]
    }
    adapter = MistralDiscoveryAdapter()
    mock_client = _FakeAsyncClient(_FakeResponse(200, payload))
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await adapter.fetch_models("fake-key")

    m = result[0]
    assert m.provider_slug == "mistral"
    assert m.raw_metadata["capabilities"]["completion_chat"] is True
    assert "Mistral Large" in m.description
    assert "128000" in m.description
    assert m.is_free is False
    assert isinstance(m.last_synced_at, datetime.datetime)


@pytest.mark.asyncio
async def test_mistral_discovery_adapter_http_401_raises():
    """A 401 from the Mistral API must raise an appropriate error."""
    from app.ai.discovery.mistral import MistralDiscoveryAdapter

    adapter = MistralDiscoveryAdapter()
    mock_client = _FakeAsyncClient(_FakeResponse(401, {"error": {"code": 401}}))
    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception) as exc_info:
            await adapter.fetch_models("bad-key")
    # httpx.HTTPStatusError for 4xx
    assert "401" in str(exc_info.value)


@pytest.mark.asyncio
async def test_mistral_discovery_adapter_http_403_raises():
    """A 403 from the Mistral API must raise an appropriate error."""
    from app.ai.discovery.mistral import MistralDiscoveryAdapter

    adapter = MistralDiscoveryAdapter()
    mock_client = _FakeAsyncClient(_FakeResponse(403, {"error": {"code": 403}}))
    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception) as exc_info:
            await adapter.fetch_models("bad-key")
    assert "403" in str(exc_info.value)


@pytest.mark.asyncio
async def test_mistral_discovery_adapter_http_500_raises():
    """A 500 from the Mistral API must raise an appropriate error."""
    from app.ai.discovery.mistral import MistralDiscoveryAdapter

    adapter = MistralDiscoveryAdapter()
    mock_client = _FakeAsyncClient(_FakeResponse(500, {"error": {"code": 500}}))
    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(Exception) as exc_info:
            await adapter.fetch_models("fake-key")
    assert "500" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2. ModelDiscoveryEngine.get_available_models("mistral", ...)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mistral_models_200_returns_chat_models():
    """A 200 response with chat models must return model IDs (embed filtered)."""
    md = _md()
    catalogue = [
        {"id": "mistral-large-latest"},
        {"id": "mistral-small-latest"},
        {"id": "mistral-embed"},  # should be filtered
    ]
    routes = {
        "api.mistral.ai": _FakeResponse(200, {"data": catalogue}),
    }
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        # Guard: the Mistral path uses a direct httpx call, NOT litellm
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError(
                "mistral must not call litellm.get_valid_models"
            ),
        ),
        patch.object(
            md.litellm, "completion", return_value={"choices": []}
        ) as mock_completion,
    ):
        models = await md.model_discovery_engine.get_available_models(
            "mistral", _FAKE_MISTRAL_KEY, force_refresh=True
        )
    assert len(models) == 2
    canonical_names = {m["canonical_model_name"] for m in models}
    assert "mistral-large-latest" in canonical_names
    assert "mistral-small-latest" in canonical_names
    assert "mistral-embed" not in canonical_names
    assert mock_completion.call_count == 2


@pytest.mark.asyncio
async def test_mistral_models_401_maps_to_provider_auth_error():
    """401 from Mistral must raise ProviderAuthError with error_type invalid_key."""
    from app.services.model_discovery import ProviderAuthError

    md = _md()
    routes = {"api.mistral.ai": _FakeResponse(401, {"error": {"code": 401}})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderAuthError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "mistral", "bad-key-00000", force_refresh=True
        )
    assert exc_info.value.error_type == "invalid_key"


@pytest.mark.asyncio
async def test_mistral_models_403_maps_to_authorization_error():
    """403 from Mistral must raise ProviderAuthError with error_type authorization_error."""
    from app.services.model_discovery import ProviderAuthError

    md = _md()
    routes = {"api.mistral.ai": _FakeResponse(403, {"error": {"code": 403}})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderAuthError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "mistral", "bad-key-00000", force_refresh=True
        )
    assert exc_info.value.error_type == "authorization_error"


@pytest.mark.asyncio
async def test_mistral_models_429_maps_to_unavailable():
    """429 from Mistral must raise ProviderUnavailableError (direct httpx path)."""
    from app.services.model_discovery import ProviderUnavailableError

    md = _md()
    routes = {"api.mistral.ai": _FakeResponse(429, {})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderUnavailableError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "mistral", _FAKE_MISTRAL_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "provider_unavailable"


@pytest.mark.asyncio
async def test_mistral_models_5xx_maps_to_unavailable():
    """5xx from Mistral must raise ProviderUnavailableError (direct httpx path)."""
    from app.services.model_discovery import ProviderUnavailableError

    md = _md()
    routes = {"api.mistral.ai": _FakeResponse(503, {})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderUnavailableError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "mistral", _FAKE_MISTRAL_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "provider_unavailable"


@pytest.mark.asyncio
async def test_mistral_models_transport_failure_is_busy():
    """Transport errors (connection reset, timeout) must raise ProviderBusyError."""
    from app.services.model_discovery import ProviderBusyError

    md = _md()
    routes = {"api.mistral.ai": ConnectionError("connection reset by peer")}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderBusyError),
    ):
        await md.model_discovery_engine.get_available_models(
            "mistral", _FAKE_MISTRAL_KEY, force_refresh=True
        )


@pytest.mark.asyncio
async def test_mistral_models_empty_catalogue_is_unavailable():
    """An empty ``data`` list must raise ProviderUnavailableError."""
    from app.services.model_discovery import ProviderUnavailableError

    md = _md()
    routes = {"api.mistral.ai": _FakeResponse(200, {"data": []})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderUnavailableError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "mistral", _FAKE_MISTRAL_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "provider_unavailable"


@pytest.mark.asyncio
async def test_mistral_models_malformed_body_is_unavailable():
    """A 200 response without a ``data`` key must raise ProviderUnavailableError."""
    from app.services.model_discovery import ProviderUnavailableError

    md = _md()
    routes = {"api.mistral.ai": _FakeResponse(200, {"unexpected": "shape"})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderUnavailableError),
    ):
        await md.model_discovery_engine.get_available_models(
            "mistral", _FAKE_MISTRAL_KEY, force_refresh=True
        )


@pytest.mark.asyncio
async def test_mistral_path_never_calls_litellm():
    """The Mistral path must use a direct httpx call and never delegate to litellm."""
    md = _md()
    catalogue = [{"id": "mistral-large-latest"}]
    routes = {"api.mistral.ai": _FakeResponse(200, {"data": catalogue})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError(
                "mistral must not call litellm.get_valid_models"
            ),
        ),
        patch.object(md.litellm, "completion", return_value={"choices": []}),
    ):
        models = await md.model_discovery_engine.get_available_models(
            "mistral", _FAKE_MISTRAL_KEY, force_refresh=True
        )
    assert len(models) == 1


@pytest.mark.asyncio
async def test_mistral_models_enriched_with_litellm_prefix():
    """Discovered Mistral models must carry the ``mistral/`` litellm prefix."""
    md = _md()
    catalogue = [{"id": "mistral-large-latest"}]
    routes = {"api.mistral.ai": _FakeResponse(200, {"data": catalogue})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm, "get_valid_models", return_value=["mistral-large-latest"]
        ),
        patch.object(md.litellm, "completion", return_value={"choices": []}),
    ):
        models = await md.model_discovery_engine.get_available_models(
            "mistral", _FAKE_MISTRAL_KEY, force_refresh=True
        )
    assert models[0]["litellm_model_name"] == "mistral/mistral-large-latest"


@pytest.mark.asyncio
async def test_mistral_models_non_chat_filtered_before_enrichment():
    """Non-chat model IDs must be excluded before enrichment/smoke tests."""
    md = _md()
    catalogue = [
        {"id": "mistral-large-latest"},
        {"id": "embedding-model"},
        {"id": "moderation-v1"},
    ]
    routes = {"api.mistral.ai": _FakeResponse(200, {"data": catalogue})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm, "completion", return_value={"choices": []}
        ) as mock_completion,
    ):
        models = await md.model_discovery_engine.get_available_models(
            "mistral", _FAKE_MISTRAL_KEY, force_refresh=True
        )
    assert len(models) == 1
    assert models[0]["canonical_model_name"] == "mistral-large-latest"
    # Only 1 smoke test fired (embed/moderation filtered out)
    assert mock_completion.call_count == 1


# ---------------------------------------------------------------------------
# 3. LLMService._resolve_model for mistral
# ---------------------------------------------------------------------------


def test_mistral_resolve_model_prepends_prefix():
    """mistral-large-latest must resolve to mistral/mistral-large-latest."""
    from app.ai.llm import llm_service

    litellm_model, _ = llm_service._resolve_model("mistral", "mistral-large-latest")
    assert litellm_model == "mistral/mistral-large-latest"


def test_mistral_resolve_model_already_prefixed():
    """If the model already has the mistral/ prefix, it must not be doubled."""
    from app.ai.llm import llm_service

    litellm_model, _ = llm_service._resolve_model(
        "mistral", "mistral/mistral-large-latest"
    )
    assert litellm_model == "mistral/mistral-large-latest"


def test_mistral_resolve_model_small():
    """Other Mistral models must also get the prefix."""
    from app.ai.llm import llm_service

    litellm_model, _ = llm_service._resolve_model("mistral", "mistral-small-latest")
    assert litellm_model == "mistral/mistral-small-latest"


# ---------------------------------------------------------------------------
# 4. Cost Estimator rates for mistral
# ---------------------------------------------------------------------------


def test_mistral_cost_rates_input():
    """Mistral input cost must be 0.002 per token."""
    from app.services.cost_estimator import cost_estimator

    rates = cost_estimator.get_rates("mistral")
    assert rates["input"] == 0.002


def test_mistral_cost_rates_output():
    """Mistral output cost must be 0.006 per token."""
    from app.services.cost_estimator import cost_estimator

    rates = cost_estimator.get_rates("mistral")
    assert rates["output"] == 0.006


def test_mistral_cost_estimator_estimate():
    """Estimate must correctly compute cost from token counts."""
    from app.services.cost_estimator import cost_estimator

    # 1000 input + 1000 output tokens
    cost = cost_estimator.estimate("mistral", 1000, 1000)
    expected = round((1000 * 0.002 + 1000 * 0.006) / 1000, 6)
    assert cost == expected


def test_mistral_cost_rates_case_insensitive():
    """Provider lookup must be case-insensitive."""
    from app.services.cost_estimator import cost_estimator

    assert cost_estimator.get_rates("MISTRAL") == {"input": 0.002, "output": 0.006}
    assert cost_estimator.get_rates("Mistral") == {"input": 0.002, "output": 0.006}


# ---------------------------------------------------------------------------
# 5. Provider registration sanity
# ---------------------------------------------------------------------------


def test_mistral_in_litellm_provider_map():
    """Mistral must be mapped in the LiteLLM provider map."""
    from app.services.model_discovery import ModelDiscoveryEngine

    assert ModelDiscoveryEngine.LITELLM_PROVIDER_MAP["mistral"] == "mistral"


def test_mistral_needs_no_api_base():
    """Mistral is a native prefix provider — no borrowed api_base."""
    from app.services.model_discovery import ModelDiscoveryEngine

    assert "mistral" not in ModelDiscoveryEngine.PROVIDER_API_BASES


def test_mistral_in_discovery_engine_adapters():
    """Mistral must be registered in the DiscoveryEngineService adapters."""
    from app.services.model_discovery import ModelDiscoveryEngine

    assert "mistral" in ModelDiscoveryEngine.LITELLM_PROVIDER_MAP


# ---------------------------------------------------------------------------
# 6. Mock keys never hit the live Mistral API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mistral_mock_key_never_hits_live_api():
    """All Mistral tests must use mocked httpx — never hit api.mistral.ai."""
    md = _md()
    catalogue = [{"id": "mistral-large-latest"}]
    routes = {"api.mistral.ai": _FakeResponse(200, {"data": catalogue})}
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(md.litellm, "completion", return_value={"choices": []}),
    ):
        _ = await md.model_discovery_engine.get_available_models(
            "mistral", _FAKE_MISTRAL_KEY, force_refresh=True
        )
    # Verify the request went to the mocked client, not the real API
    assert len(fake.calls) == 1
    assert "api.mistral.ai" in fake.calls[0]["args"][0]


@pytest.mark.asyncio
async def test_mistral_discovery_adapter_never_hits_live_api():
    """MistralDiscoveryAdapter.fetch_models must use the mocked httpx client."""
    from app.ai.discovery.mistral import MistralDiscoveryAdapter

    payload = {"data": [{"id": "mistral-large-latest", "name": "Mistral Large"}]}
    mock_client = _FakeAsyncClient(_FakeResponse(200, payload))
    with patch("httpx.AsyncClient", return_value=mock_client):
        adapter = MistralDiscoveryAdapter()
        result = await adapter.fetch_models("fake-key")
    assert len(result) == 1
    assert result[0].model_id == "mistral-large-latest"


# ---------------------------------------------------------------------------
# 7. Endpoint integration (mocked discovery)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_individual_test_mistral_success(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    """A successful Mistral validation must mark the key as valid."""
    mock_models.return_value = [{"canonical_model_name": "mistral-large-latest"}]
    key = await _make_key(test_db, mock_user)
    response = client.post(f"/api/v1/api-keys/{key.id}/test")
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    await test_db.refresh(key)
    assert key.is_valid is True


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_individual_test_mistral_invalid_key(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    """A Mistral auth failure must mark the key as invalid."""
    from app.services.model_discovery import ProviderAuthError

    mock_models.side_effect = ProviderAuthError(
        "Invalid API key.", error_type="invalid_key"
    )
    key = await _make_key(test_db, mock_user)
    response = client.post(f"/api/v1/api-keys/{key.id}/test")
    assert response.status_code == 400
    assert "Invalid API key" in response.json()["detail"]
    await test_db.refresh(key)
    assert key.is_valid is False


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_mistral_success(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    """Validate-all with a valid Mistral key must report success."""
    mock_models.return_value = [{"canonical_model_name": "mistral-large-latest"}]
    key = await _make_key(test_db, mock_user)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    assert data["results"][str(key.id)]["status"] == "success"
    assert data["summary"] == {"total": 1, "succeeded": 1, "failed": 0, "busy": 0}


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_mistral_busy_preserves_validity(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    """A transient Mistral busy error must not auto-invalidated the key."""
    from app.services.model_discovery import ProviderUnavailableError

    mock_models.side_effect = ProviderUnavailableError(
        "Provider returned no usable models.",
        error_type="provider_unavailable",
    )
    key = await _make_key(test_db, mock_user)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    r = data["results"][str(key.id)]
    assert r["status"] == "busy"
    await test_db.refresh(key)
    assert key.is_valid is True
