"""Tests for bulk Validate All (POST /api/v1/api-keys/validate-all).

Covers: empty state, success paths, invalid/busy classification, timeout,
decryption failure, unknown provider, mixed partial results, persistence
isolation, auth, secret sanitization, and discovery-layer correctness
(NVIDIA/Cohere 401-403, quota auth failures, cache behavior).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encryption_service
from app.models.api_key import ApiKey
from app.models.health import ApiKeyHealth


async def _make_key(test_db, mock_user, provider="gemini", label="K", raw="test-key-value-12345", is_valid=True):
    key = ApiKey(
        user_id=mock_user.id,
        provider=provider,
        label=label,
        encrypted_key=encryption_service.encrypt(raw),
        is_valid=is_valid,
    )
    test_db.add(key)
    await test_db.commit()
    await test_db.refresh(key)
    return key


def _result(data, key):
    return data["results"][str(key.id)]


# --- endpoint: basic shapes -------------------------------------------------

@pytest.mark.asyncio
async def test_validate_all_no_keys(client: TestClient):
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    assert data["results"] == {}
    assert data["summary"] == {"total": 0, "succeeded": 0, "failed": 0, "busy": 0}


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_one_valid_key(mock_models, client, test_db, mock_user):
    mock_models.return_value = [{"id": "m1"}]
    key = await _make_key(test_db, mock_user)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    r = _result(data, key)
    assert r["status"] == "success"
    assert r["error_type"] is None
    assert data["summary"] == {"total": 1, "succeeded": 1, "failed": 0, "busy": 0}
    await test_db.refresh(key)
    assert key.is_valid is True


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_multiple_valid_keys(mock_models, client, test_db, mock_user):
    mock_models.return_value = [{"id": "m1"}, {"id": "m2"}]
    k1 = await _make_key(test_db, mock_user, label="A")
    k2 = await _make_key(test_db, mock_user, label="B", provider="openai")
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    assert _result(data, k1)["status"] == "success"
    assert _result(data, k2)["status"] == "success"
    assert data["summary"] == {"total": 2, "succeeded": 2, "failed": 0, "busy": 0}


# --- endpoint: failure classification ---------------------------------------

@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_invalid_401(mock_models, client, test_db, mock_user):
    mock_models.side_effect = Exception("Invalid API Key credentials — 401 unauthorized")
    key = await _make_key(test_db, mock_user, is_valid=True)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200  # partial result, not HTTP error
    r = _result(response.json(), key)
    assert r["status"] == "failed"
    assert r["error_type"] == "invalid_key"
    assert r["message"] == "Invalid API key."
    await test_db.refresh(key)
    assert key.is_valid is False


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_forbidden_403(mock_models, client, test_db, mock_user):
    mock_models.side_effect = Exception("403 forbidden: permission denied")
    key = await _make_key(test_db, mock_user, is_valid=True)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    r = _result(response.json(), key)
    assert r["status"] == "failed"
    assert r["error_type"] == "authorization_error"
    await test_db.refresh(key)
    assert key.is_valid is False


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_rate_limited_429_preserves_validity(
    mock_models, client, test_db, mock_user
):
    mock_models.side_effect = Exception("429 rate_limit_exceeded")
    key = await _make_key(test_db, mock_user, is_valid=True)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    r = _result(response.json(), key)
    assert r["status"] == "busy"
    assert r["error_type"] == "rate_limited"
    assert response.json()["summary"]["busy"] == 1
    await test_db.refresh(key)
    assert key.is_valid is True  # busy must not invalidate


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_provider_503_busy(mock_models, client, test_db, mock_user):
    mock_models.side_effect = Exception("503 Service Unavailable")
    key = await _make_key(test_db, mock_user, is_valid=False)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    r = _result(response.json(), key)
    assert r["status"] == "busy"
    assert r["error_type"] == "provider_unavailable"
    await test_db.refresh(key)
    assert key.is_valid is False  # previous state preserved


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_provider_timeout_busy(mock_models, client, test_db, mock_user):
    mock_models.side_effect = asyncio.TimeoutError()
    key = await _make_key(test_db, mock_user, is_valid=True)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    r = _result(response.json(), key)
    assert r["status"] == "busy"
    assert r["error_type"] == "timeout"
    await test_db.refresh(key)
    assert key.is_valid is True


@pytest.mark.asyncio
async def test_validate_all_decryption_failure_isolated(client, test_db, mock_user):
    bad = ApiKey(
        user_id=mock_user.id,
        provider="gemini",
        label="Corrupt",
        encrypted_key="!!!not-fernet!!!",
        is_valid=True,
    )
    test_db.add(bad)
    await test_db.commit()
    await test_db.refresh(bad)
    with patch(
        "app.services.model_discovery.model_discovery_engine.get_available_models",
        return_value=[{"id": "m"}],
    ):
        response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    r = _result(response.json(), bad)
    assert r["status"] == "failed"
    assert r["error_type"] == "decryption_error"


@pytest.mark.asyncio
async def test_validate_all_unknown_provider(client, test_db, mock_user):
    key = await _make_key(test_db, mock_user, provider="mystery_provider")
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    r = _result(response.json(), key)
    assert r["status"] == "failed"
    assert r["error_type"] == "unknown_provider"


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_mixed_partial_results(mock_models, client, test_db, mock_user):
    good = await _make_key(test_db, mock_user, label="good", is_valid=False, raw="good-key-value-11111")
    bad = await _make_key(test_db, mock_user, label="bad", is_valid=True, raw="bad-key-value-22222")
    busy_key = await _make_key(test_db, mock_user, label="busy", is_valid=True, raw="busy-key-value-33333")

    async def _route(provider, raw, force_refresh=False):
        if raw == encryption_service.decrypt(good.encrypted_key):
            return [{"id": "m"}]
        if raw == encryption_service.decrypt(bad.encrypted_key):
            raise Exception("401 unauthorized")
        raise Exception("429 rate limited")

    mock_models.side_effect = _route
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    assert _result(data, good)["status"] == "success"
    assert _result(data, bad)["status"] == "failed"
    assert _result(data, busy_key)["status"] == "busy"
    assert data["summary"] == {"total": 3, "succeeded": 1, "failed": 1, "busy": 1}
    await test_db.refresh(good)
    await test_db.refresh(bad)
    await test_db.refresh(busy_key)
    assert good.is_valid is True
    assert bad.is_valid is False
    assert busy_key.is_valid is True


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_persistence_isolated_per_key(
    mock_models, client, test_db, mock_user
):
    """One key's health-write failure must not abort the remaining keys."""
    from app.services.api_key_service import api_key_service as svc

    mock_models.return_value = [{"id": "m"}]
    k1 = await _make_key(test_db, mock_user, label="k1")
    k2 = await _make_key(test_db, mock_user, label="k2")

    real_record = svc.record_health
    calls = {"n": 0}

    async def _flaky(db, key_id, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("health store boom")
        return await real_record(db, key_id, *args, **kwargs)

    with patch.object(svc, "record_health", side_effect=_flaky):
        response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    assert _result(data, k1)["status"] == "success"
    assert _result(data, k2)["status"] == "success"
    assert data["summary"]["succeeded"] == 2


@pytest.mark.asyncio
async def test_validate_all_requires_auth(test_db, mock_user):
    """Without the auth override, missing JWT must yield 401 (not generic 200)."""
    from fastapi.testclient import TestClient

    from app.core.deps import get_current_user
    from app.db.session import get_db
    from app.main import app

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop(get_current_user, None)
    try:
        with TestClient(app, raise_server_exceptions=False) as anon:
            response = anon.post("/api/v1/api-keys/validate-all")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_sanitizes_secrets(mock_models, client, test_db, mock_user):
    secret = "sk-SECRETabcdef1234567890"
    mock_models.side_effect = Exception(f"401 bad key {secret} Bearer TOKXYZ")
    key = await _make_key(test_db, mock_user)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    r = _result(response.json(), key)
    assert secret not in r["message"]
    assert "TOKXYZ" not in r["message"]
    result = await test_db.execute(
        select(ApiKeyHealth).where(ApiKeyHealth.key_id == key.id)
    )
    records = result.scalars().all()
    assert records, "expected a health record"
    for rec in records:
        assert rec.error_message is None or secret not in rec.error_message
        assert rec.error_message is None or "TOKXYZ" not in rec.error_message


# --- discovery layer ----------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


@pytest.mark.asyncio
async def test_nvidia_401_is_auth_failure_not_fallback():
    from app.services.model_discovery import ProviderAuthError, model_discovery_engine

    fake = _FakeAsyncClient(_FakeResponse(401, {"data": [{"id": "x"}]}))
    with patch("httpx.AsyncClient", return_value=fake):
        with pytest.raises(ProviderAuthError):
            await model_discovery_engine.get_available_models(
                "nvidia", "nvapi-bad-key-1234567890", force_refresh=True
            )


@pytest.mark.asyncio
async def test_nvidia_403_is_auth_failure_not_fallback():
    from app.services.model_discovery import ProviderAuthError, model_discovery_engine

    fake = _FakeAsyncClient(_FakeResponse(403, {"data": [{"id": "x"}]}))
    with patch("httpx.AsyncClient", return_value=fake):
        with pytest.raises(ProviderAuthError):
            await model_discovery_engine.get_available_models(
                "nvidia", "nvapi-bad-key-1234567890", force_refresh=True
            )


@pytest.mark.asyncio
async def test_cohere_401_is_auth_failure():
    from app.services.model_discovery import ProviderAuthError, model_discovery_engine

    fake = _FakeAsyncClient(_FakeResponse(401, {"models": []}))
    with patch("httpx.AsyncClient", return_value=fake):
        with pytest.raises(ProviderAuthError):
            await model_discovery_engine.get_available_models(
                "cohere", "cohere-bad-key-1234567890", force_refresh=True
            )


@pytest.mark.asyncio
async def test_cohere_403_is_auth_failure():
    from app.services.model_discovery import ProviderAuthError, model_discovery_engine

    fake = _FakeAsyncClient(_FakeResponse(403, {"models": []}))
    with patch("httpx.AsyncClient", return_value=fake):
        with pytest.raises(ProviderAuthError):
            await model_discovery_engine.get_available_models(
                "cohere", "cohere-bad-key-1234567890", force_refresh=True
            )


@pytest.mark.asyncio
async def test_verify_model_quota_401_is_failure_not_soft_success():
    from types import SimpleNamespace

    from app.services import model_discovery as md

    stub = SimpleNamespace(
        canonical_model_name="test-model", litellm_model_name="openai/gpt-4o"
    )
    # Patch the litellm object model_discovery actually references (another
    # test module swaps sys.modules["litellm"], so patch("litellm...") would
    # miss in full-suite runs).
    with patch.object(
        md.litellm, "completion", side_effect=Exception("401 Unauthorized")
    ):
        assert await md.model_discovery_engine.verify_model_quota(stub, "k") is False
        accessible, saw_auth = await md.model_discovery_engine.verify_model_quota_detailed(
            stub, "k"
        )
        assert (accessible, saw_auth) == (False, True)


@pytest.mark.asyncio
async def test_verify_model_quota_403_is_failure_not_soft_success():
    from types import SimpleNamespace

    from app.services import model_discovery as md

    stub = SimpleNamespace(
        canonical_model_name="test-model", litellm_model_name="openai/gpt-4o"
    )
    with patch.object(md.litellm, "completion", side_effect=Exception("403 Forbidden")):
        assert await md.model_discovery_engine.verify_model_quota(stub, "k") is False


@pytest.mark.asyncio
async def test_verify_model_quota_transient_retains_accessible():
    from types import SimpleNamespace

    from app.services import model_discovery as md

    stub = SimpleNamespace(
        canonical_model_name="test-model", litellm_model_name="openai/gpt-4o"
    )
    with patch.object(
        md.litellm, "completion", side_effect=Exception("503 Service Unavailable")
    ):
        assert await md.model_discovery_engine.verify_model_quota(stub, "k") is True
    with patch.object(
        md.litellm, "completion", side_effect=Exception("429 rate limited")
    ):
        assert await md.model_discovery_engine.verify_model_quota(stub, "k") is True


@pytest.mark.asyncio
async def test_success_cached_and_failure_not_cached():
    from app.services import model_discovery as md

    md._MODEL_CACHE.clear()
    # Patch the litellm object model_discovery references (see note above).
    with (
        patch.object(md.litellm, "get_valid_models", return_value=["gpt-4o"]) as mock_list,
        patch.object(md.litellm, "completion", return_value={"choices": []}),
    ):
        first = await md.model_discovery_engine.get_available_models("openai", "sk-valid-key-1234567890")
        second = await md.model_discovery_engine.get_available_models("openai", "sk-valid-key-1234567890")
        assert len(first) >= 1
        assert first == second
        assert mock_list.call_count == 1  # second served from cache

    md._MODEL_CACHE.clear()
    with patch.object(
        md.litellm,
        "get_valid_models",
        side_effect=Exception("401 Unauthorized"),
    ) as mock_list:
        from app.services.model_discovery import ProviderAuthError

        with pytest.raises(ProviderAuthError):
            await md.model_discovery_engine.get_available_models("openai", "sk-bad-key-0000000000")
        with pytest.raises(ProviderAuthError):
            await md.model_discovery_engine.get_available_models("openai", "sk-bad-key-0000000000")
        assert mock_list.call_count == 2  # failures never cached


@pytest.mark.asyncio
async def test_validate_all_uses_fresh_discovery_not_stale_cache(
    client, test_db, mock_user
):
    """Bulk validation bypasses a stale success cache (force refresh)."""
    from app.services import model_discovery as md

    md._MODEL_CACHE.clear()
    key = await _make_key(test_db, mock_user, provider="openai", raw="sk-fresh-key-1234567890")
    with (
        patch.object(md.litellm, "get_valid_models", return_value=["gpt-4o"]) as mock_list,
        patch.object(md.litellm, "completion", return_value={"choices": []}),
    ):
        # Prime the cache with a success.
        await md.model_discovery_engine.get_available_models("openai", "sk-fresh-key-1234567890")
        assert mock_list.call_count == 1
        # Bulk validation must revalidate rather than trust the cache.
        response = client.post("/api/v1/api-keys/validate-all")
        assert response.status_code == 200
        assert _result(response.json(), key)["status"] == "success"
        assert mock_list.call_count == 2
