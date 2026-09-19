"""Ollama Cloud validation regression tests.

Root cause covered here: Ollama Cloud borrows LiteLLM's ``openai`` provider
prefix, so every LiteLLM call (model list AND quota smoke tests) must carry
``api_base="https://ollama.com/v1"``. The smoke test previously omitted it,
routing completions to api.openai.com whose 401 misreported valid Ollama
Cloud credentials as invalid.

All credentials below are fake/mocked. Never use a real key in tests.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encryption_service
from app.models.api_key import ApiKey

_FAKE_KEY = "test-ollama-cloud-key-00000"


def _md():
    from app.services import model_discovery as md

    md._MODEL_CACHE.clear()
    return md


async def _make_key(test_db, mock_user, provider="ollama_cloud", raw=_FAKE_KEY):
    key = ApiKey(
        user_id=mock_user.id,
        provider=provider,
        label=f"Test {provider}",
        encrypted_key=encryption_service.encrypt(raw),
        is_valid=False,
    )
    test_db.add(key)
    await test_db.commit()
    await test_db.refresh(key)
    return key


@pytest.mark.asyncio
async def test_ollama_cloud_smoke_test_uses_cloud_base():
    """Quota smoke completions must target ollama.com, not api.openai.com."""
    md = _md()
    with (
        patch.object(
            md.litellm, "get_valid_models", return_value=["qwen3:32b"]
        ),
        patch.object(
            md.litellm, "completion", return_value={"choices": []}
        ) as mock_completion,
    ):
        models = await md.model_discovery_engine.get_available_models(
            "ollama_cloud", _FAKE_KEY, force_refresh=True
        )
    assert len(models) >= 1
    assert mock_completion.call_count >= 1
    for call in mock_completion.call_args_list:
        assert call.kwargs.get("api_base") == "https://ollama.com/v1"
        assert call.kwargs.get("model", "").startswith("openai/")


@pytest.mark.asyncio
async def test_ollama_cloud_401_at_cloud_base_is_invalid():
    """A genuine 401 from Ollama Cloud must still classify as invalid."""
    from app.services.model_discovery import ProviderAuthError

    md = _md()
    with (
        patch.object(md.litellm, "get_valid_models", return_value=["qwen3:32b"]),
        patch.object(
            md.litellm, "completion", side_effect=Exception("401 Unauthorized")
        ),
    ):
        with pytest.raises(ProviderAuthError):
            await md.model_discovery_engine.get_available_models(
                "ollama_cloud", _FAKE_KEY, force_refresh=True
            )


@pytest.mark.asyncio
async def test_other_providers_pass_no_api_base():
    """Providers with native prefixes must be unaffected (api_base=None)."""
    md = _md()
    with (
        patch.object(
            md.litellm, "get_valid_models", return_value=["llama-3.3-70b-versatile"]
        ),
        patch.object(
            md.litellm, "completion", return_value={"choices": []}
        ) as mock_completion,
    ):
        models = await md.model_discovery_engine.get_available_models(
            "groq", "test-groq-key-00000", force_refresh=True
        )
    assert len(models) >= 1
    for call in mock_completion.call_args_list:
        assert call.kwargs.get("api_base") is None


def test_ollama_cloud_mapping_sanity():
    from app.services.model_discovery import ModelDiscoveryEngine

    assert ModelDiscoveryEngine.LITELLM_PROVIDER_MAP["ollama_cloud"] == "openai"
    assert (
        ModelDiscoveryEngine.PROVIDER_API_BASES["ollama_cloud"]
        == "https://ollama.com/v1"
    )


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_individual_test_ollama_cloud_success(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    mock_models.return_value = [{"id": "qwen3:32b"}]
    key = await _make_key(test_db, mock_user)
    response = client.post(f"/api/v1/api-keys/{key.id}/test")
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    await test_db.refresh(key)
    assert key.is_valid is True


@pytest.mark.asyncio
@patch("app.services.model_discovery.model_discovery_engine.get_available_models")
async def test_individual_test_ollama_cloud_invalid(
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
async def test_validate_all_ollama_cloud_success(
    mock_models, client: TestClient, test_db: AsyncSession, mock_user
):
    mock_models.return_value = [{"id": "qwen3:32b"}]
    key = await _make_key(test_db, mock_user)
    response = client.post("/api/v1/api-keys/validate-all")
    assert response.status_code == 200
    data = response.json()
    assert data["results"][str(key.id)]["status"] == "success"
    assert data["summary"] == {"total": 1, "succeeded": 1, "failed": 0, "busy": 0}
