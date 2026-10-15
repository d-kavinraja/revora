"""OpenRouter validation regression tests.

Root cause covered here: OpenRouter's catalogue is ~300 models (vs ~20-30
for NVIDIA/Gemini). Validation used to smoke-test ALL of them with unbounded
concurrency — hundreds of paid 1-token completions that drew 429s and blew
the 22s per-key budget, surfacing as perpetual TEST BUSY. Validation now:

1. checks the credential first via the documented, free, non-generative
   ``GET https://openrouter.ai/api/v1/key`` endpoint (200 = valid with
   quota evidence, 401 = invalid), and
2. smoke-tests only a small sampled prefix with bounded concurrency
   (OPENROUTER_SMOKE_SAMPLE_SIZE / OPENROUTER_SMOKE_CONCURRENCY).

Also covered: HTTP 402 / exhausted credit is never a soft success and never
an auth verdict (new ``insufficient_credits`` error type, busy-preserving),
and OpenRouter-only unknown-4xx exclusion (other providers keep the legacy
retain behaviour).

All credentials below are fake/mocked. Never use a real key in tests.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encryption_service
from app.models.api_key import ApiKey

_FAKE_KEY = "sk-or-v1-test-key-0000000000000000"


def _md():
    from app.services import model_discovery as md

    md._MODEL_CACHE.clear()
    return md


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


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


async def _make_key(test_db, mock_user, provider="openrouter", raw=_FAKE_KEY, is_valid=True):
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


def _key_ok_payload(remaining=74.5, free_tier=False):
    return {
        "data": {
            "label": "sk-or-v1-test...0000",
            "limit": 100,
            "limit_remaining": remaining,
            "usage": 25.5,
            "is_free_tier": free_tier,
        }
    }


# --- /key pre-check ----------------------------------------------------------

@pytest.mark.asyncio
async def test_openrouter_key_200_with_balance_is_valid():
    md = _md()
    fake = _FakeAsyncClient(_FakeResponse(200, _key_ok_payload()))
    with patch("httpx.AsyncClient", return_value=fake):
        await md.ModelDiscoveryEngine._verify_openrouter_key(_FAKE_KEY)
    assert len(fake.calls) == 1
    assert fake.calls[0]["args"][0] == "https://openrouter.ai/api/v1/key"
    assert fake.calls[0]["kwargs"]["headers"]["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_openrouter_key_401_is_invalid():
    from app.services.model_discovery import ProviderAuthError

    md = _md()
    fake = _FakeAsyncClient(_FakeResponse(401, {"error": {"code": 401}}))
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderAuthError) as exc_info,
    ):
        await md.ModelDiscoveryEngine._verify_openrouter_key("sk-or-v1-bad")
    assert exc_info.value.error_type == "invalid_key"


@pytest.mark.asyncio
async def test_openrouter_key_403_is_authorization_error():
    from app.services.model_discovery import ProviderAuthError

    md = _md()
    fake = _FakeAsyncClient(_FakeResponse(403, {}))
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderAuthError) as exc_info,
    ):
        await md.ModelDiscoveryEngine._verify_openrouter_key(_FAKE_KEY)
    assert exc_info.value.error_type == "authorization_error"


@pytest.mark.asyncio
async def test_openrouter_key_429_is_busy_not_invalid():
    from app.services.model_discovery import ProviderBusyError

    md = _md()
    fake = _FakeAsyncClient(_FakeResponse(429, {}))
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderBusyError) as exc_info,
    ):
        await md.ModelDiscoveryEngine._verify_openrouter_key(_FAKE_KEY)
    assert exc_info.value.error_type == "rate_limited"


@pytest.mark.asyncio
async def test_openrouter_key_5xx_is_busy_not_invalid():
    from app.services.model_discovery import ProviderBusyError

    md = _md()
    fake = _FakeAsyncClient(_FakeResponse(503, {}))
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderBusyError),
    ):
        await md.ModelDiscoveryEngine._verify_openrouter_key(_FAKE_KEY)


@pytest.mark.asyncio
async def test_openrouter_key_transport_failure_is_busy():
    from app.services.model_discovery import ProviderBusyError

    md = _md()
    fake = _FakeAsyncClient(ConnectionError("connection reset by peer"))
    with (
        patch("httpx.AsyncClient", return_value=fake),
        pytest.raises(ProviderBusyError),
    ):
        await md.ModelDiscoveryEngine._verify_openrouter_key(_FAKE_KEY)


@pytest.mark.asyncio
async def test_openrouter_key_zero_balance_returns_exhausted_evidence_not_raise():
    """Zero paid balance is evidence, not a verdict: never raises."""
    md = _md()
    fake = _FakeAsyncClient(_FakeResponse(200, _key_ok_payload(remaining=0)))
    with patch("httpx.AsyncClient", return_value=fake):
        exhausted = await md.ModelDiscoveryEngine._verify_openrouter_key(_FAKE_KEY)
    assert exhausted is True


@pytest.mark.asyncio
async def test_openrouter_key_free_tier_zero_balance_never_exhausted():
    """Free-tier keys are never balance-exhausted: paid balance is
    irrelevant to free models (regression for the reported false
    insufficient-credits warning)."""
    md = _md()
    fake = _FakeAsyncClient(
        _FakeResponse(200, _key_ok_payload(remaining=0, free_tier=True))
    )
    with patch("httpx.AsyncClient", return_value=fake):
        exhausted = await md.ModelDiscoveryEngine._verify_openrouter_key(_FAKE_KEY)
    assert exhausted is False


@pytest.mark.asyncio
async def test_openrouter_key_null_limit_skips_balance_check():
    md = _md()
    payload = {"data": {"label": "free-key", "limit": None, "limit_remaining": None}}
    fake = _FakeAsyncClient(_FakeResponse(200, payload))
    with patch("httpx.AsyncClient", return_value=fake):
        await md.ModelDiscoveryEngine._verify_openrouter_key(_FAKE_KEY)


def _free_entry(model_id):
    return {"id": model_id, "pricing": {"prompt": "0", "completion": "0"}}


def _paid_entry(model_id):
    return {
        "id": model_id,
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
    }


def _openrouter_routes(catalogue, key_payload=None):
    """Route /key and /models to distinct fakes for the OpenRouter path.

    Accepts model-id strings (treated as opaque entries, no pricing) or
    full catalogue entry dicts (with pricing for free/paid distinction).
    """
    entries = (
        catalogue
        if catalogue and isinstance(catalogue[0], dict)
        else [{"id": m} for m in catalogue]
    )
    return {
        "api/v1/key": _FakeResponse(200, _key_ok_payload() if key_payload is None else key_payload),
        "api/v1/models": _FakeResponse(
            200, {"data": entries}
        ),
    }


# --- bounded smoke fan-out ---------------------------------------------------

@pytest.mark.asyncio
async def test_openrouter_smokes_are_bounded_not_catalogue_sized():
    """300-model catalogue must not produce 300 completion calls; smokes
    must target eligible free models even when they sit beyond the paid
    catalogue prefix (regression for the reported false credit warning)."""
    md = _md()
    catalogue = [_paid_entry(f"testvendor/paid-{i}") for i in range(300)]
    catalogue += [_free_entry(f"testvendor/freemodel-{i}:free") for i in range(30)]
    fake = _FakeAsyncClient(None, routes=_openrouter_routes(catalogue))
    with (
        patch("httpx.AsyncClient", return_value=fake),
        # The OpenRouter path must never consult litellm's model list:
        # the installed LiteLLM resolves no provider config for it and its
        # static fallback list is empty, which used to force perpetual busy.
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        patch.object(md.litellm, "completion", return_value={"choices": []}) as mock_completion,
    ):
        models = await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert len(models) >= 1  # full catalogue still listed
    assert mock_completion.call_count <= md.ModelDiscoveryEngine.OPENROUTER_SMOKE_SAMPLE_SIZE
    assert mock_completion.call_count >= 1
    for call in mock_completion.call_args_list:
        smoked = call.kwargs.get("model", "")
        assert smoked.startswith("openrouter/")
        assert smoked.endswith(":free")  # free models preferred, paid prefix skipped
    key_urls = [c["args"][0] for c in fake.calls]
    assert "https://openrouter.ai/api/v1/key" in key_urls
    assert "https://openrouter.ai/api/v1/models" in key_urls


@pytest.mark.asyncio
async def test_openrouter_zero_paid_credits_free_model_succeeds():
    """The reported scenario: free-tier key, zero paid balance, but an
    accessible free model — validation must succeed, never insufficient."""
    md = _md()
    catalogue = [_paid_entry("testvendor/paid")] + [
        _free_entry("testvendor/freemodel:free")
    ]
    routes = _openrouter_routes(
        catalogue, key_payload=_key_ok_payload(remaining=0, free_tier=True)
    )
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        patch.object(md.litellm, "completion", return_value={"choices": []}),
    ):
        models = await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert any(m["canonical_model_name"] == "testvendor/freemodel:free" for m in models)


@pytest.mark.asyncio
async def test_other_providers_keep_unbounded_smokes():
    """The cap is OpenRouter-scoped; groq behaviour is unchanged."""
    md = _md()
    catalogue = [f"testmodel-{i}" for i in range(30)]
    with (
        patch.object(md.litellm, "get_valid_models", return_value=catalogue),
        patch.object(md.litellm, "completion", return_value={"choices": []}) as mock_completion,
    ):
        models = await md.model_discovery_engine.get_available_models(
            "groq", "test-groq-key-00000", force_refresh=True
        )
    assert len(models) == 30
    assert mock_completion.call_count == 30


# --- 402 / unknown-4xx classification ----------------------------------------

@pytest.mark.asyncio
async def test_openrouter_all_402_is_insufficient_credits():
    from types import SimpleNamespace

    from app.services import model_discovery as md
    from app.services.model_discovery import ProviderBusyError

    stub = SimpleNamespace(
        canonical_model_name="testmodel",
        litellm_model_name="openrouter/testvendor/testmodel",
        provider="openrouter",
    )
    with patch.object(
        md.litellm,
        "completion",
        side_effect=Exception("402 Payment Required: insufficient credits"),
    ):
        accessible, saw_auth = await md.model_discovery_engine.verify_model_quota_detailed(
            stub, "k", credit_sink=[]
        )
        assert (accessible, saw_auth) == (False, False)

    key_client = _FakeAsyncClient(
        None, routes=_openrouter_routes([_free_entry("testvendor/testmodel:free")])
    )
    with (
        patch("httpx.AsyncClient", return_value=key_client),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        patch.object(
            md.litellm,
            "completion",
            side_effect=Exception("402 Payment Required: insufficient credits"),
        ),
        pytest.raises(ProviderBusyError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "insufficient_credits"


# --- free-model-first verdicts ---------------------------------------------

@pytest.mark.asyncio
async def test_openrouter_paid_only_catalogue_never_spends_paid_smokes():
    """Paid-only catalogue: validation must not fire paid completions and
    must report no_free_model (busy) — never invalid, never credits."""
    from app.services.model_discovery import ProviderBusyError

    md = _md()
    fake = _FakeAsyncClient(
        None,
        routes=_openrouter_routes(
            [_paid_entry(f"testvendor/paid-{i}") for i in range(12)]
        ),
    )
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        patch.object(
            md.litellm, "completion", return_value={"choices": []}
        ) as mock_completion,
        pytest.raises(ProviderBusyError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "no_free_model"
    assert mock_completion.call_count == 0  # no paid smoke was spent


@pytest.mark.asyncio
async def test_openrouter_paid_only_catalogue_with_exhausted_balance_is_credits():
    """Genuine paid-balance evidence (non-free-tier, exhausted limit) plus a
    paid-only catalogue is the one case where insufficient_credits stands."""
    from app.services.model_discovery import ProviderBusyError

    md = _md()
    fake = _FakeAsyncClient(
        None,
        routes=_openrouter_routes(
            [_paid_entry("testvendor/paid")],
            key_payload=_key_ok_payload(remaining=0),
        ),
    )
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        patch.object(
            md.litellm, "completion", return_value={"choices": []}
        ) as mock_completion,
        pytest.raises(ProviderBusyError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "insufficient_credits"
    assert mock_completion.call_count == 0


@pytest.mark.asyncio
async def test_openrouter_free_smokes_all_unreachable_is_no_free_model():
    """Free models exist but none verifiable (e.g. no endpoints): busy
    no_free_model — a valid key is never reported invalid or broke."""
    from app.services.model_discovery import ProviderBusyError

    md = _md()
    fake = _FakeAsyncClient(
        None,
        routes=_openrouter_routes(
            [_paid_entry("testvendor/paid")]
            + [_free_entry(f"testvendor/free-{i}:free") for i in range(3)]
        ),
    )
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        patch.object(
            md.litellm,
            "completion",
            side_effect=Exception("404 Not Found: No endpoints found for model"),
        ),
        pytest.raises(ProviderBusyError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "no_free_model"


# --- direct /models list branch ---------------------------------------------

@pytest.mark.asyncio
async def test_openrouter_models_401_is_invalid():
    from app.services.model_discovery import ProviderAuthError

    md = _md()
    routes = dict(_openrouter_routes(["testvendor/testmodel"]))
    routes["api/v1/models"] = _FakeResponse(401, {})
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        pytest.raises(ProviderAuthError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "invalid_key"


@pytest.mark.asyncio
async def test_openrouter_models_403_is_authorization_error():
    from app.services.model_discovery import ProviderAuthError

    md = _md()
    routes = dict(_openrouter_routes(["testvendor/testmodel"]))
    routes["api/v1/models"] = _FakeResponse(403, {})
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        pytest.raises(ProviderAuthError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "authorization_error"


@pytest.mark.asyncio
async def test_openrouter_models_429_is_rate_limited_busy():
    from app.services.model_discovery import ProviderBusyError

    md = _md()
    routes = dict(_openrouter_routes(["testvendor/testmodel"]))
    routes["api/v1/models"] = _FakeResponse(429, {})
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        pytest.raises(ProviderBusyError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "rate_limited"


@pytest.mark.asyncio
async def test_openrouter_models_5xx_is_busy_not_invalid():
    from app.services.model_discovery import ProviderBusyError

    md = _md()
    routes = dict(_openrouter_routes(["testvendor/testmodel"]))
    routes["api/v1/models"] = _FakeResponse(503, {})
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        pytest.raises(ProviderBusyError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "provider_unavailable"


@pytest.mark.asyncio
async def test_openrouter_models_transport_failure_is_busy_not_invalid():
    from app.services.model_discovery import ProviderBusyError

    md = _md()
    routes = dict(_openrouter_routes(["testvendor/testmodel"]))
    routes["api/v1/models"] = ConnectionError("connection reset by peer")
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        pytest.raises(ProviderBusyError),
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )


@pytest.mark.asyncio
async def test_openrouter_models_empty_catalogue_is_unavailable():
    from app.services.model_discovery import ProviderUnavailableError

    md = _md()
    routes = dict(_openrouter_routes([]))
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        pytest.raises(ProviderUnavailableError) as exc_info,
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )
    assert exc_info.value.error_type == "provider_unavailable"


@pytest.mark.asyncio
async def test_openrouter_models_malformed_body_is_unavailable():
    from app.services.model_discovery import ProviderUnavailableError

    md = _md()
    routes = dict(_openrouter_routes([]))
    routes["api/v1/models"] = _FakeResponse(200, {"unexpected": "shape"})
    fake = _FakeAsyncClient(None, routes=routes)
    with (
        patch("httpx.AsyncClient", return_value=fake),
        patch.object(
            md.litellm,
            "get_valid_models",
            side_effect=AssertionError("must not be called for openrouter"),
        ),
        pytest.raises(ProviderUnavailableError),
    ):
        await md.model_discovery_engine.get_available_models(
            "openrouter", _FAKE_KEY, force_refresh=True
        )


@pytest.mark.asyncio
async def test_openrouter_unknown_4xx_excluded_not_retained():
    from types import SimpleNamespace

    from app.services import model_discovery as md

    stub = SimpleNamespace(
        canonical_model_name="testmodel",
        litellm_model_name="openrouter/testvendor/testmodel",
        provider="openrouter",
    )
    with patch.object(
        md.litellm, "completion", side_effect=Exception("400 Bad Request: bad model")
    ):
        accessible, saw_auth = await md.model_discovery_engine.verify_model_quota_detailed(
            stub, "k"
        )
        assert (accessible, saw_auth) == (False, False)


@pytest.mark.asyncio
async def test_other_provider_unknown_4xx_still_retained():
    """Legacy retain-on-unknown is preserved for non-OpenRouter providers."""
    from types import SimpleNamespace

    from app.services import model_discovery as md

    for provider in ("groq", None):
        stub_kwargs = {
            "canonical_model_name": "testmodel",
            "litellm_model_name": "groq/testmodel",
        }
        if provider is not None:
            stub_kwargs["provider"] = provider
        stub = SimpleNamespace(**stub_kwargs)
        with patch.object(
            md.litellm, "completion", side_effect=Exception("400 Bad Request: bad model")
        ):
            assert await md.model_discovery_engine.verify_model_quota(stub, "k") is True


def test_classify_402_is_insufficient_credits():
    from app.services.model_discovery import ProviderBusyError, classify_provider_error

    error_type, _, exc_cls = classify_provider_error(
        Exception("402 Payment Required: insufficient credits for this request")
    )
    assert error_type == "insufficient_credits"
    assert exc_cls is ProviderBusyError


def test_classify_401_429_unchanged():
    from app.services.model_discovery import (
        ProviderAuthError,
        ProviderBusyError,
        classify_provider_error,
    )

    assert classify_provider_error(Exception("401 Unauthorized"))[2] is ProviderAuthError
    assert classify_provider_error(Exception("429 rate limited"))[2] is ProviderBusyError


def test_openrouter_mapping_sanity():
    from app.services.model_discovery import ModelDiscoveryEngine

    assert ModelDiscoveryEngine.LITELLM_PROVIDER_MAP["openrouter"] == "openrouter"
    assert "openrouter" not in ModelDiscoveryEngine.PROVIDER_API_BASES
    assert ModelDiscoveryEngine.OPENROUTER_SMOKE_SAMPLE_SIZE <= 10
    assert ModelDiscoveryEngine.OPENROUTER_SMOKE_CONCURRENCY <= 4


# --- endpoint behaviour ------------------------------------------------------

@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_openrouter_insufficient_credits_preserves_validity(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    from app.services.model_discovery import ProviderBusyError

    mock_models.side_effect = ProviderBusyError(
        "The provider key has insufficient credits.",
        error_type="insufficient_credits",
    )
    key = await _make_key(test_db, mock_user, is_valid=True)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    r = data["results"][str(key.id)]
    assert r["status"] == "busy"
    assert r["error_type"] == "insufficient_credits"
    assert "credits" in r["message"].lower()
    assert data["summary"] == {"total": 1, "succeeded": 0, "failed": 0, "busy": 1}
    await test_db.refresh(key)
    assert key.is_valid is True  # transient: never auto-invalidated


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_openrouter_timeout_preserves_validity(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    from app.services.model_discovery import ProviderBusyError

    mock_models.side_effect = ProviderBusyError(
        "Validation timed out.", error_type="timeout"
    )
    key = await _make_key(test_db, mock_user, is_valid=True)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    r = response.json()["results"][str(key.id)]
    assert r["status"] == "busy"
    assert r["error_type"] == "timeout"
    await test_db.refresh(key)
    assert key.is_valid is True


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_openrouter_no_free_model_preserves_validity(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    from app.services.model_discovery import ProviderBusyError

    mock_models.side_effect = ProviderBusyError(
        "No free model could be verified with this key.",
        error_type="no_free_model",
    )
    key = await _make_key(test_db, mock_user, is_valid=True)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    r = data["results"][str(key.id)]
    assert r["status"] == "busy"
    assert r["error_type"] == "no_free_model"
    assert "add credits" not in r["message"].lower()
    assert data["summary"] == {"total": 1, "succeeded": 0, "failed": 0, "busy": 1}
    await test_db.refresh(key)
    assert key.is_valid is True  # valid key, only free-model access unverified


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_individual_test_openrouter_invalid_key(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
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
