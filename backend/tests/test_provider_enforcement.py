"""C1 provider/credential enforcement tests (B34-B38).

Closes F1-F7: every user-facing surface must refuse blocked providers and
disabled credentials, while preserving zero-state parity and reversibility.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.auth import SESSION_COOKIE_NAME
from app.core.security import encryption_service
from app.models.api_key import ApiKey
from app.models.github import Installation, Repository
from app.models.provider import ProviderRegistry
from app.services import api_key_service as aks

RAW_KEY = "sk-c1-openai-123456"


async def _seed_provider(db, *, name="openai", status="available", is_enabled=True, status_message=None, allow_key_addition=True):
    provider = ProviderRegistry(
        name=name,
        display_name=name.title(),
        slug=name,
        litellm_provider=name,
        default_model="gpt-4o-mini",
        status=status,
        is_enabled=is_enabled,
        allow_key_addition=allow_key_addition,
        status_message=status_message,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


async def _seed_key(db, user, *, provider="openai", is_enabled=True):
    key = ApiKey(
        user_id=user.id,
        provider=provider,
        label="Primary",
        encrypted_key=encryption_service.encrypt(RAW_KEY),
        is_valid=True,
        is_enabled=is_enabled,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


async def _seed_repo(db, user):
    installation = Installation(
        installation_id=99003,
        account_id=4244,
        account_login="acct",
        account_type="User",
        user_id=user.id,
        repository_selection="all",
        permissions={},
        events={},
    )
    db.add(installation)
    await db.commit()
    await db.refresh(installation)
    repo = Repository(
        github_id=88003,
        name="c1demo",
        full_name="acct/c1demo",
        installation_id=installation.id,
        reviews_enabled=True,
        settings={},
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return repo


def _as_user(anon_client, token):
    anon_client.cookies.set(SESSION_COOKIE_NAME, token)
    return anon_client


# ---------------------------------------------------------------------------
# B34 — /llm/execute refuses blocked provider (explicit path)
# ---------------------------------------------------------------------------


async def test_b34_llm_execute_blocked_provider(test_db, anon_client, user_auth_token, mock_user):
    await _seed_provider(test_db, status="disabled", is_enabled=False, status_message="Provider disabled by admin.")
    await _seed_key(test_db, mock_user)

    client = _as_user(anon_client, user_auth_token)
    response = client.post(
        "/api/v1/llm/execute",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "preferred_provider": "openai",
            "preferred_model": "gpt-4o-mini",
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Provider disabled by admin."


# ---------------------------------------------------------------------------
# B35 — /llm/execute refuses disabled credential (explicit api_key_id)
# ---------------------------------------------------------------------------


async def test_b35_llm_execute_disabled_credential(test_db, anon_client, user_auth_token, mock_user):
    await _seed_provider(test_db)
    key = await _seed_key(test_db, mock_user, is_enabled=False)

    client = _as_user(anon_client, user_auth_token)
    response = client.post(
        "/api/v1/llm/execute",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "preferred_provider": "openai",
            "preferred_model": "gpt-4o-mini",
            "api_key_id": str(key.id),
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Invalid API key selected."


# ---------------------------------------------------------------------------
# B36 — restricted listings exclude blocked providers/credentials
# ---------------------------------------------------------------------------


async def test_b36_models_listing_excludes_blocked(test_db, anon_client, user_auth_token, mock_user, monkeypatch):
    await _seed_provider(test_db, status="disabled", is_enabled=False)
    await _seed_key(test_db, mock_user)

    from app.services import model_discovery as md

    async def fake_models(provider_name, raw_key):
        return ["gpt-4o-mini"]

    monkeypatch.setattr(md.model_discovery_engine, "get_available_models", fake_models)

    client = _as_user(anon_client, user_auth_token)
    response = client.get("/api/v1/models")
    assert response.status_code == 200, response.text
    assert "openai" not in response.json()


async def test_b36_models_per_provider_excludes_blocked(test_db, anon_client, user_auth_token, mock_user, monkeypatch):
    await _seed_provider(test_db, status="disabled", is_enabled=False)
    await _seed_key(test_db, mock_user)

    from app.services import model_discovery as md

    async def fake_models(provider_name, raw_key):
        return [{"canonical_model_name": "gpt-4o-mini", "litellm_model_name": "openai/gpt-4o-mini", "accessible": True}]

    monkeypatch.setattr(md.model_discovery_engine, "get_available_models", fake_models)

    client = _as_user(anon_client, user_auth_token)
    response = client.get("/api/v1/routing/models-per-provider")
    assert response.status_code == 200, response.text
    assert "openai" not in response.json()


async def test_b36_available_models_excludes_blocked(test_db, anon_client, user_auth_token, mock_user):
    await _seed_provider(test_db, status="disabled", is_enabled=False)
    await _seed_key(test_db, mock_user)

    client = _as_user(anon_client, user_auth_token)
    response = client.get("/api/v1/repositories/available-models")
    assert response.status_code == 200, response.text
    assert "openai" not in response.json()


# ---------------------------------------------------------------------------
# B37 — repo config PATCH refuses disabled credential; settings unchanged
# ---------------------------------------------------------------------------


async def test_b37_repo_config_disabled_credential(test_db, anon_client, user_auth_token, mock_user):
    await _seed_provider(test_db)
    key = await _seed_key(test_db, mock_user, is_enabled=False)
    repo = await _seed_repo(test_db, mock_user)

    client = _as_user(anon_client, user_auth_token)
    before = dict(repo.settings or {})
    response = client.patch(
        f"/api/v1/repositories/{repo.id}/config",
        json={
            "assigned_provider": "openai",
            "assigned_model": "gpt-4o-mini",
            "assigned_key_id": str(key.id),
        },
    )
    assert response.status_code == 400, response.text

    await test_db.refresh(repo)
    assert (repo.settings or {}) == before


# ---------------------------------------------------------------------------
# B38 — transition matrix: disable -> re-enable restores byte-identical config
# ---------------------------------------------------------------------------


async def test_b38_provider_transition_matrix(test_db, anon_client, user_auth_token, mock_user):
    provider = await _seed_provider(test_db)
    await _seed_key(test_db, mock_user)
    repo = await _seed_repo(test_db, mock_user)

    client = _as_user(anon_client, user_auth_token)

    # Baseline mapping succeeds.
    first = client.patch(
        f"/api/v1/repositories/{repo.id}/config",
        json={"assigned_provider": "openai", "assigned_model": "gpt-4o-mini"},
    )
    assert first.status_code == 200, first.text
    await test_db.refresh(repo)
    baseline_settings = dict(repo.settings or {})

    # Disable provider -> mapping refused.
    provider.status = "disabled"
    provider.is_enabled = False
    test_db.add(provider)
    await test_db.commit()

    blocked = client.patch(
        f"/api/v1/repositories/{repo.id}/config",
        json={"assigned_provider": "openai", "assigned_model": "gpt-4o-mini"},
    )
    assert blocked.status_code == 400, blocked.text
    await test_db.refresh(repo)
    assert dict(repo.settings or {}) == baseline_settings

    # Re-enable -> mapping succeeds again with identical settings.
    provider.status = "available"
    provider.is_enabled = True
    test_db.add(provider)
    await test_db.commit()

    restored = client.patch(
        f"/api/v1/repositories/{repo.id}/config",
        json={"assigned_provider": "openai", "assigned_model": "gpt-4o-mini"},
    )
    assert restored.status_code == 200, restored.text
    await test_db.refresh(repo)
    assert dict(repo.settings or {}) == baseline_settings


async def test_b38_credential_transition_matrix(test_db, anon_client, user_auth_token, mock_user, monkeypatch):
    await _seed_provider(test_db)
    key = await _seed_key(test_db, mock_user)
    repo = await _seed_repo(test_db, mock_user)

    from app.services import model_discovery as md

    async def fake_models(provider_name, raw_key):
        return [{"canonical_model_name": "gpt-4o-mini", "accessible": True}]

    monkeypatch.setattr(md.model_discovery_engine, "get_available_models", fake_models)

    client = _as_user(anon_client, user_auth_token)

    first = client.patch(
        f"/api/v1/repositories/{repo.id}/config",
        json={
            "assigned_provider": "openai",
            "assigned_model": "gpt-4o-mini",
            "assigned_key_id": str(key.id),
        },
    )
    assert first.status_code == 200, first.text
    await test_db.refresh(repo)
    baseline_settings = dict(repo.settings or {})

    # Disable credential -> mapping refused.
    key.is_enabled = False
    test_db.add(key)
    await test_db.commit()

    blocked = client.patch(
        f"/api/v1/repositories/{repo.id}/config",
        json={
            "assigned_provider": "openai",
            "assigned_model": "gpt-4o-mini",
            "assigned_key_id": str(key.id),
        },
    )
    assert blocked.status_code == 400, blocked.text
    await test_db.refresh(repo)
    assert dict(repo.settings or {}) == baseline_settings

    # Re-enable -> mapping succeeds again.
    key.is_enabled = True
    test_db.add(key)
    await test_db.commit()

    restored = client.patch(
        f"/api/v1/repositories/{repo.id}/config",
        json={
            "assigned_provider": "openai",
            "assigned_model": "gpt-4o-mini",
            "assigned_key_id": str(key.id),
        },
    )
    assert restored.status_code == 200, restored.text
    await test_db.refresh(repo)
    assert dict(repo.settings or {}) == baseline_settings