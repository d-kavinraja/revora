"""Groq provider integration tests.

Covers registration, API-key validation/storage, live-discovery
normalization (mocked), deprecation handling, cost/metadata enrichment,
LLM execution routing, and error mapping for the Groq provider.

Groq is a NATIVE LiteLLM provider: model IDs take the ``groq/`` prefix
(including slashed IDs such as ``groq/openai/gpt-oss-120b``) and no
custom ``api_base`` is required — LiteLLM routes ``groq/`` to
https://api.groq.com/openai/v1 internally. Every test below asserts
``api_base is None`` on LiteLLM calls to guard against regressions of
the borrow-prefix bug class seen with ollama_cloud.

All credentials below are fake/mocked. Never use a real key in tests.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encryption_service
from app.models.api_key import ApiKey
from app.services.model_discovery import ModelDiscoveryEngine

_Fake_GROQ_KEY = "gsk_test_fake_groq_key_00000"


def _md():
    from app.services import model_discovery as md

    md._MODEL_CACHE.clear()
    return md


async def _make_key(test_db, mock_user, raw=_Fake_GROQ_KEY):
    key = ApiKey(
        user_id=mock_user.id,
        provider="groq",
        label="Test Groq",
        encrypted_key=encryption_service.encrypt(raw),
        is_valid=False,
    )
    test_db.add(key)
    await test_db.commit()
    await test_db.refresh(key)
    return key


# ---------------------------------------------------------------------------
# Provider registration
# ---------------------------------------------------------------------------


def test_groq_in_litellm_provider_map():
    assert ModelDiscoveryEngine.LITELLM_PROVIDER_MAP["groq"] == "groq"


def test_groq_needs_no_api_base():
    """Native prefix providers must not carry a borrowed-provider api_base."""
    assert "groq" not in ModelDiscoveryEngine.PROVIDER_API_BASES


def test_groq_error_classifier_known():
    from app.services.model_discovery import classify_provider_error

    assert classify_provider_error(Exception("401 Unauthorized"))[2].__name__ == (
        "ProviderAuthError"
    )
    assert classify_provider_error(Exception("429 rate limit"))[2].__name__ == (
        "ProviderBusyError"
    )


# ---------------------------------------------------------------------------
# API key validation / storage / redaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_groq_key_requires_gsk_prefix(
    client: TestClient, test_db: AsyncSession
):
    response = client.post(
        "/api/v1/api-keys",
        json={"provider": "groq", "label": "test", "api_key": "sk-1234567890abcdef"},
    )
    assert response.status_code == 422
    assert "gsk_" in response.json()["detail"]

    response = client.post(
        "/api/v1/api-keys",
        json={"provider": "groq", "label": "test", "api_key": _Fake_GROQ_KEY},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["provider"] == "groq"
    assert "api_key" not in data

    result = await test_db.execute(
        select(ApiKey).where(ApiKey.id == uuid.UUID(data["id"]))
    )
    db_key = result.scalars().first()
    assert db_key is not None
    assert db_key.encrypted_key != _Fake_GROQ_KEY
    assert encryption_service.decrypt(db_key.encrypted_key) == _Fake_GROQ_KEY


def test_groq_key_redacted_from_errors():
    from app.api.v1.endpoints.api_keys import sanitize_error_message

    leaked = f"connection failed for key {_Fake_GROQ_KEY} Bearer {_Fake_GROQ_KEY}"
    cleaned = sanitize_error_message(leaked)
    assert _Fake_GROQ_KEY not in cleaned
    assert "[redacted]" in cleaned


# ---------------------------------------------------------------------------
# Model discovery: normalization, non-chat filtering, deprecation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_discovery_normalizes_and_filters():
    """Live IDs normalize to groq/ litellm names; audio/guard/agentic drop."""
    md = _md()
    live_ids = [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "whisper-large-v3-turbo",
        "openai/gpt-oss-safeguard-20b",
        "groq/compound",
        "meta-llama/llama-prompt-guard-2-22m",
    ]
    with (
        patch.object(md.litellm, "get_valid_models", return_value=live_ids),
        patch.object(
            md.litellm, "completion", return_value={"choices": []}
        ) as mock_completion,
    ):
        models = await md.model_discovery_engine.get_available_models(
            "groq", _Fake_GROQ_KEY, force_refresh=True
        )
    by_canonical = {m["canonical_model_name"]: m for m in models}
    assert "openai/gpt-oss-20b" in by_canonical
    assert "openai/gpt-oss-120b" in by_canonical
    assert "openai/gpt-oss-safeguard-20b" in by_canonical
    # Non-chat families excluded before enrichment/smoke tests
    assert not any("whisper" in k for k in by_canonical)
    assert not any("compound" in k for k in by_canonical)
    assert not any("prompt-guard" in k for k in by_canonical)
    for m in models:
        assert m["litellm_model_name"].startswith("groq/")
        assert m["accessible"] is True
    for call in mock_completion.call_args_list:
        assert call.kwargs.get("api_base") is None
        assert call.kwargs.get("model", "").startswith("groq/")


@pytest.mark.asyncio
async def test_groq_deprecated_models_flagged():
    """Groq-retired IDs (e.g. llama-3.3) enrich as deprecated."""
    md = _md()
    with (
        patch.object(
            md.litellm,
            "get_valid_models",
            return_value=["llama-3.3-70b-versatile", "openai/gpt-oss-120b"],
        ),
        patch.object(md.litellm, "completion", return_value={"choices": []}),
    ):
        models = await md.model_discovery_engine.get_available_models(
            "groq", _Fake_GROQ_KEY, force_refresh=True
        )
    by_canonical = {m["canonical_model_name"]: m for m in models}
    assert by_canonical["llama-3.3-70b-versatile"]["deprecated"] is True
    assert by_canonical["llama-3.3-70b-versatile"]["status"] == "deprecated"
    assert by_canonical["openai/gpt-oss-120b"]["deprecated"] is False


@pytest.mark.asyncio
async def test_groq_metadata_enrichment():
    """Official pricing/context overlay applies; reasoning/tool flags set."""
    md = _md()
    with (
        patch.object(
            md.litellm, "get_valid_models", return_value=["openai/gpt-oss-120b"]
        ),
        patch.object(md.litellm, "completion", return_value={"choices": []}),
    ):
        models = await md.model_discovery_engine.get_available_models(
            "groq", _Fake_GROQ_KEY, force_refresh=True
        )
    assert len(models) == 1
    m = models[0]
    assert m["context_window"] == 131072
    assert m["input_cost"] == pytest.approx(0.15 / 1_000_000)
    assert m["output_cost"] == pytest.approx(0.60 / 1_000_000)
    assert m["supports_reasoning"] is True
    assert m["supports_function_calling"] is True


@pytest.mark.asyncio
async def test_groq_preview_model_flagged():
    md = _md()
    with (
        patch.object(
            md.litellm,
            "get_valid_models",
            return_value=["openai/gpt-oss-safeguard-20b"],
        ),
        patch.object(md.litellm, "completion", return_value={"choices": []}),
    ):
        models = await md.model_discovery_engine.get_available_models(
            "groq", _Fake_GROQ_KEY, force_refresh=True
        )
    assert models[0]["preview"] is True
    assert models[0]["status"] == "preview"


@pytest.mark.asyncio
async def test_groq_auth_failure_is_invalid():
    from app.services.model_discovery import ProviderAuthError

    md = _md()
    with (
        patch.object(
            md.litellm,
            "get_valid_models",
            return_value=["openai/gpt-oss-120b"],
        ),
        patch.object(
            md.litellm, "completion", side_effect=Exception("401 Unauthorized")
        ),
        pytest.raises(ProviderAuthError),
    ):
        await md.model_discovery_engine.get_available_models(
            "groq", "gsk_wrong_key_00000", force_refresh=True
        )


@pytest.mark.asyncio
async def test_groq_empty_catalog_is_unavailable():
    from app.services.model_discovery import ProviderUnavailableError

    md = _md()
    with (
        patch.object(md.litellm, "get_valid_models", return_value=[]),
        pytest.raises(ProviderUnavailableError),
    ):
        await md.model_discovery_engine.get_available_models(
            "groq", _Fake_GROQ_KEY, force_refresh=True
        )


# ---------------------------------------------------------------------------
# LLM execution routing + cost
# ---------------------------------------------------------------------------


def test_groq_model_resolution_uses_native_prefix():
    from app.ai.llm import llm_service

    litellm_name, _ = llm_service._resolve_model("groq", "openai/gpt-oss-120b")
    assert litellm_name == "groq/openai/gpt-oss-120b"
    litellm_name, _ = llm_service._resolve_model("groq", "llama-3.3-70b-versatile")
    assert litellm_name == "groq/llama-3.3-70b-versatile"


def test_groq_cost_rates_current():
    from app.services.cost_estimator import cost_estimator

    rates = cost_estimator.get_rates("groq")
    # GPT-OSS 120B flagship: $0.15/$0.60 per 1M == per-1K below
    assert rates == {"input": 0.00015, "output": 0.0006}


# ---------------------------------------------------------------------------
# Endpoint integration (mocked discovery)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_individual_test_groq_success(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    mock_models.return_value = [{"id": "openai/gpt-oss-120b"}]
    key = await _make_key(test_db, mock_user)
    response = client.post(f"/api/v1/api-keys/{key.id}/test")
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    await test_db.refresh(key)
    assert key.is_valid is True


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_individual_test_groq_invalid(
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


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_validate_all_groq_success(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    mock_models.return_value = [{"id": "openai/gpt-oss-120b"}]
    key = await _make_key(test_db, mock_user)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    assert data["results"][str(key.id)]["status"] == "success"
    assert data["summary"] == {"total": 1, "succeeded": 1, "failed": 0, "busy": 0}
