"""Provider/credential control tests.

Phase 1 lockdown (D8): `PUT /providers/{slug}`, `POST /providers/{slug}/toggle`
and `POST /providers/{slug}/sync-models` were session-authenticated with no
role check (verified privilege-escalation hole). After the lockdown:
anonymous -> 401, authenticated non-admin -> 403, admin -> handler runs.

Phase 4 (plan §9/§10, tests B16-B22): admin-disabled providers and
disabled credentials are blocked on every enforcement surface — repo
mappings, routing preferences, review resolution (fail fast, no
substitution), key addition, credential selection and fallback — while
remaining fully non-destructive (S7) and reversible without user action.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.auth import SESSION_COOKIE_NAME
from app.core.security import encryption_service
from app.github.shared import resolve_provider_config
from app.middleware.rate_limit import limiter
from app.models.api_key import ApiKey
from app.models.audit import AuditLog
from app.models.github import Installation, Repository
from app.models.health import ApiKeyHealth
from app.models.provider import ProviderRegistry
from app.services import api_key_service as aks
from app.services.provider_registry import ProviderUnavailableError

PROVIDER_WRITE_ROUTES = [
    ("PUT", "/api/v1/providers/openai", {"display_name": "Nope"}),
    ("POST", "/api/v1/providers/openai/toggle", {"is_enabled": False}),
    ("POST", "/api/v1/providers/openai/sync-models", None),
]

RAW_KEY = "sk-test-openai-key-123456"


# ---------------------------------------------------------------------------
# Phase 1 lockdown (unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path,body", PROVIDER_WRITE_ROUTES)
def test_anonymous_provider_writes_rejected(anon_client, method, path, body):
    response = anon_client.request(method, path, json=body)
    assert response.status_code == 401, (method, path, response.text)


@pytest.mark.parametrize("method,path,body", PROVIDER_WRITE_ROUTES)
def test_regular_user_provider_writes_forbidden(
    anon_client, user_auth_token, method, path, body
):
    # Cookie session, mirroring the browser flow the fallback path reads.
    anon_client.cookies.set(SESSION_COOKIE_NAME, user_auth_token)
    response = anon_client.request(method, path, json=body)
    assert response.status_code == 403, (method, path, response.text)
    assert response.json()["detail"] == "Admin privileges required"


def test_admin_passes_authorization_layer(admin_client):
    # Unknown slug: authz must pass and the handler 404s (empty registry).
    response = admin_client.put(
        "/api/v1/providers/nonexistent-provider", json={"display_name": "X"}
    )
    assert response.status_code == 404


def test_provider_listing_remains_available_to_users(client):
    response = client.get("/api/v1/providers")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Phase 4 fixtures / helpers
# ---------------------------------------------------------------------------


async def _seed_provider(
    db,
    *,
    name: str = "openai",
    status: str = "available",
    is_enabled: bool = True,
    allow_key_addition: bool = True,
    status_message: str | None = None,
) -> ProviderRegistry:
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


async def _seed_key(
    db, user, *, provider: str = "openai", is_enabled: bool = True
) -> ApiKey:
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


async def _seed_repo(db, user, *, settings: dict | None = None) -> Repository:
    installation = Installation(
        installation_id=99001,
        account_id=4242,
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
        github_id=88001,
        name="demo",
        full_name="acct/demo",
        installation_id=installation.id,
        reviews_enabled=True,
        settings=settings or {},
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return repo


def _as_user(anon_client, user_auth_token):
    anon_client.cookies.set(SESSION_COOKIE_NAME, user_auth_token)
    return anon_client


async def _audit_rows(db, action: str):
    result = await db.execute(select(AuditLog).where(AuditLog.action == action))
    return result.scalars().all()


# ---------------------------------------------------------------------------
# B16 — repo mapping rejected while the provider is blocked
# ---------------------------------------------------------------------------


async def test_b16_repo_mapping_rejected_for_disabled_provider(
    test_db, anon_client, user_auth_token, mock_user
):
    await _seed_provider(test_db, status="disabled", is_enabled=False)
    key = await _seed_key(test_db, mock_user)
    repo = await _seed_repo(test_db, mock_user)

    client = _as_user(anon_client, user_auth_token)
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
    assert "assigned_provider" not in (repo.settings or {})
    assert "assigned_model" not in (repo.settings or {})
    assert "assigned_key_id" not in (repo.settings or {})


async def test_b22_mapping_restored_after_reenable(
    test_db, anon_client, user_auth_token, mock_user
):
    provider = await _seed_provider(test_db, status="disabled", is_enabled=False)
    await _seed_key(test_db, mock_user)
    repo = await _seed_repo(test_db, mock_user)

    client = _as_user(anon_client, user_auth_token)
    blocked = client.patch(
        f"/api/v1/repositories/{repo.id}/config",
        json={"assigned_provider": "openai", "assigned_model": "gpt-4o-mini"},
    )
    assert blocked.status_code == 400

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
    assert repo.settings["assigned_provider"] == "openai"
    assert repo.settings["assigned_model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# B17 — routing preferences rejected while the provider is blocked
# ---------------------------------------------------------------------------


async def test_b17_routing_preferences_reject_blocked_provider(
    test_db, anon_client, user_auth_token, mock_user
):
    await _seed_provider(test_db, name="openai", status="disabled", is_enabled=False)
    mock_user.settings = {
        "model_routing": {"code_review": {"provider": "anthropic", "model": "claude"}}
    }
    test_db.add(mock_user)
    await test_db.commit()

    client = _as_user(anon_client, user_auth_token)
    response = client.put(
        "/api/v1/routing/preferences",
        json={"routing": {"code_review": {"provider": "openai", "model": "gpt-4o-mini"}}},
    )
    assert response.status_code == 400, response.text

    stored = client.get("/api/v1/routing/preferences").json()["routing"]
    assert stored["code_review"]["provider"] == "anthropic"


async def test_b17_routing_accepts_available_provider_zero_state(
    test_db, anon_client, user_auth_token, mock_user
):
    await _seed_provider(test_db, name="openai", status="available")
    client = _as_user(anon_client, user_auth_token)
    response = client.put(
        "/api/v1/routing/preferences",
        json={"routing": {"code_review": {"provider": "openai", "model": "gpt-4o-mini"}}},
    )
    assert response.status_code == 200, response.text
    stored = client.get("/api/v1/routing/preferences").json()["routing"]
    assert stored["code_review"]["provider"] == "openai"


# ---------------------------------------------------------------------------
# B18 — resolution fails fast, never substitutes
# ---------------------------------------------------------------------------


async def test_b18_mode1_fails_fast_and_never_substitutes(
    test_db, mock_user
):
    provider = await _seed_provider(test_db, status="disabled", is_enabled=False)
    key = await _seed_key(test_db, mock_user)
    # A usable alternative exists (MODE 2 candidate) — must NOT be used.
    await _seed_provider(test_db, name="anthropic", status="available")
    await _seed_key(test_db, mock_user, provider="anthropic")
    mock_user.settings = {
        "model_routing": {"code_review": {"provider": "anthropic", "model": "claude"}}
    }
    test_db.add(mock_user)
    await test_db.commit()

    repo = await _seed_repo(
        test_db,
        mock_user,
        settings={
            "assigned_provider": "openai",
            "assigned_model": "gpt-4o-mini",
            "assigned_key_id": str(key.id),
        },
    )

    with pytest.raises(ProviderUnavailableError) as excinfo:
        await resolve_provider_config(test_db, mock_user.id, repo)
    assert excinfo.value.provider == "openai"

    # Mapping is retained (never auto-cleaned) — only re-enable restores it.
    await test_db.refresh(repo)
    assert repo.settings["assigned_provider"] == "openai"
    assert repo.settings["assigned_key_id"] == str(key.id)

    provider.status = "available"
    provider.is_enabled = True
    test_db.add(provider)
    await test_db.commit()

    resolved = await resolve_provider_config(test_db, mock_user.id, repo)
    assert resolved == ("openai", "gpt-4o-mini", str(key.id), "repo_config")


async def test_b18_credential_disable_breaks_mode1_key_validity(test_db, mock_user):
    await _seed_provider(test_db)
    key = await _seed_key(test_db, mock_user, is_enabled=False)
    repo = await _seed_repo(
        test_db,
        mock_user,
        settings={
            "assigned_provider": "openai",
            "assigned_model": "gpt-4o-mini",
            "assigned_key_id": str(key.id),
        },
    )
    # Disabled credential = invalid key for MODE 1 → stale-mapping cleanup,
    # which is the pre-existing behavior for unusable keys (not a block).
    resolved = await resolve_provider_config(test_db, mock_user.id, repo)
    assert resolved == (None, None, None, "none")


# ---------------------------------------------------------------------------
# B19 — key-addition policy
# ---------------------------------------------------------------------------


async def test_b19_blocked_provider_rejects_new_keys_keeps_existing(
    test_db, anon_client, user_auth_token, mock_user, monkeypatch
):
    provider = await _seed_provider(
        test_db, status="disabled", is_enabled=False
    )
    existing = await _seed_key(test_db, mock_user)
    before_encrypted = existing.encrypted_key
    before_count = len(
        (await test_db.execute(select(ApiKey.id))).scalars().all()
    )

    client = _as_user(anon_client, user_auth_token)
    response = client.post(
        "/api/v1/api-keys",
        json={"provider": "openai", "label": "New", "api_key": "sk-second-key-123456"},
    )
    assert response.status_code == 400, response.text

    await test_db.refresh(existing)
    assert existing.encrypted_key == before_encrypted
    after_count = len(
        (await test_db.execute(select(ApiKey.id))).scalars().all()
    )
    assert after_count == before_count

    # Allow-list policy while the provider is otherwise available.
    provider.status = "available"
    provider.is_enabled = True
    provider.allow_key_addition = False
    test_db.add(provider)
    await test_db.commit()

    monkeypatch.setattr(
        "app.services.model_discovery.warm_model_cache",
        lambda *args, **kwargs: None,
    )
    disallowed = client.post(
        "/api/v1/api-keys",
        json={"provider": "openai", "label": "New", "api_key": "sk-second-key-123456"},
    )
    assert disallowed.status_code == 400

    # Re-enable the policy → creation works again (no user config needed).
    provider.allow_key_addition = True
    test_db.add(provider)
    await test_db.commit()

    allowed = client.post(
        "/api/v1/api-keys",
        json={"provider": "openai", "label": "New", "api_key": "sk-second-key-123456"},
    )
    assert allowed.status_code == 201, allowed.text


async def test_b19_under_testing_allows_keys_when_policy_permits(
    test_db, anon_client, user_auth_token, mock_user, monkeypatch
):
    await _seed_provider(
        test_db, status="under_testing", allow_key_addition=True
    )
    monkeypatch.setattr(
        "app.services.model_discovery.warm_model_cache",
        lambda *args, **kwargs: None,
    )
    client = _as_user(anon_client, user_auth_token)
    response = client.post(
        "/api/v1/api-keys",
        json={"provider": "openai", "label": "Test", "api_key": "sk-under-test-123456"},
    )
    assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------
# B20 — credential disable/exclude everywhere, re-enable restores
# ---------------------------------------------------------------------------


async def test_b20_disabled_credential_excluded_from_all_selection(
    test_db, anon_client, user_auth_token, mock_user
):
    await _seed_provider(test_db)
    key = await _seed_key(test_db, mock_user)

    client = _as_user(anon_client, user_auth_token)
    disabled = client.post(f"/api/v1/api-keys/{key.id}/disable")
    assert disabled.status_code == 200, disabled.text

    await test_db.refresh(key)
    assert key.is_enabled is False

    assert await aks.get_all_usable_keys(test_db, mock_user.id) == {}
    assert await aks.get_usable_key(test_db, mock_user.id, "openai") is None
    assert await aks.get_decrypted_key(test_db, mock_user.id, "openai") is None
    assert (
        await aks.get_all_decrypted_keys(test_db, mock_user.id, "openai")
        == []
    )

    # Fallback/MODE 2 see no usable key → nothing to execute with.
    mock_user.settings = {
        "model_routing": {"code_review": {"provider": "openai", "model": "gpt-4o-mini"}}
    }
    test_db.add(mock_user)
    await test_db.commit()
    resolved = await resolve_provider_config(test_db, mock_user.id, None)
    assert resolved == (None, None, None, "none")

    enabled = client.post(f"/api/v1/api-keys/{key.id}/enable")
    assert enabled.status_code == 200
    await test_db.refresh(key)
    assert key.is_enabled is True
    usable = await aks.get_all_usable_keys(test_db, mock_user.id)
    assert list(usable.keys()) == ["openai"]

    resolved = await resolve_provider_config(test_db, mock_user.id, None)
    assert resolved == ("openai", "gpt-4o-mini", str(key.id), "user_routing")


async def test_admin_credential_controls_metadata_only_and_audited(
    admin_client, test_db, mock_user, admin_user
):
    await _seed_provider(test_db)
    key = await _seed_key(test_db, mock_user)

    response = admin_client.post(f"/api/v1/admin/keys/{key.id}/disable")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_enabled"] is False
    assert "encrypted_key" not in body
    assert "masked_key" not in body

    await test_db.refresh(key)
    assert key.is_enabled is False
    assert encryption_service.decrypt(key.encrypted_key) == RAW_KEY

    rows = await _audit_rows(test_db, "admin.credential_disabled")
    assert len(rows) == 1
    assert rows[0].actor_id == admin_user.username
    assert rows[0].details["provider"] == "openai"

    enabled = admin_client.post(f"/api/v1/admin/keys/{key.id}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["is_enabled"] is True
    assert len(await _audit_rows(test_db, "admin.credential_enabled")) == 1

    missing = admin_client.post(f"/api/v1/admin/keys/{uuid.uuid4()}/disable")
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# B21 — outage status never mass-flips credential validity
# ---------------------------------------------------------------------------


async def test_b21_unavailable_status_preserves_key_validity(
    test_db, anon_client, user_auth_token, mock_user
):
    await _seed_provider(
        test_db, status="unavailable", status_message="Provider outage — back soon."
    )
    key = await _seed_key(test_db, mock_user)

    client = _as_user(anon_client, user_auth_token)
    listing = client.get("/api/v1/api-keys")
    assert listing.status_code == 200
    listed = [k for k in listing.json() if k["id"] == str(key.id)]
    assert len(listed) == 1
    assert listed[0]["is_valid"] is True

    await test_db.refresh(key)
    assert key.is_valid is True

    # New key addition blocked (default for outages) — existing key untouched.
    blocked = client.post(
        "/api/v1/api-keys",
        json={"provider": "openai", "label": "New", "api_key": "sk-outage-key-123456"},
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "Provider outage — back soon."

    health_rows = (await test_db.execute(select(ApiKeyHealth.id))).scalars().all()
    assert health_rows == []


# ---------------------------------------------------------------------------
# Admin provider endpoints (§18) — aggregates, audit, conflict rules
# ---------------------------------------------------------------------------


async def test_admin_provider_list_aggregates(admin_client, test_db, mock_user):
    await _seed_provider(test_db)
    key = await _seed_key(test_db, mock_user)
    await _seed_key(test_db, mock_user, is_enabled=False)
    await _seed_repo(
        test_db,
        mock_user,
        settings={"assigned_provider": "openai", "assigned_model": "gpt-4o-mini"},
    )

    response = admin_client.get("/api/v1/admin/providers")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["slug"] == "openai"
    assert row["status"] == "available"
    assert row["keys_total"] == 2
    assert row["keys_enabled"] == 1
    assert row["keys_valid"] == 2
    assert row["mapped_repositories"] == 1
    assert row["last_health_status"] is None
    assert key.id


async def test_admin_provider_update_transitions_and_audits(
    admin_client, test_db, anon_client, user_auth_token
):
    await _seed_provider(test_db)

    unknown = admin_client.put(
        "/api/v1/admin/providers/ghost", json={"status": "unavailable"}
    )
    assert unknown.status_code == 404

    invalid = admin_client.put(
        "/api/v1/admin/providers/openai", json={"status": "banana"}
    )
    assert invalid.status_code == 400

    conflict = admin_client.put(
        "/api/v1/admin/providers/openai",
        json={"status": "disabled", "is_enabled": True},
    )
    assert conflict.status_code == 409

    unavailable = admin_client.put(
        "/api/v1/admin/providers/openai",
        json={"status": "unavailable", "status_message": "Outage — ETA 30 min."},
    )
    assert unavailable.status_code == 200, unavailable.text
    body = unavailable.json()
    assert body["status"] == "unavailable"
    assert body["status_message"] == "Outage — ETA 30 min."
    assert body["is_enabled"] is True

    rows = await _audit_rows(test_db, "admin.provider_status_changed")
    assert len(rows) == 1
    assert rows[0].details["changes"]["status"] == "unavailable"

    # Users see the outage status + message on the ordinary providers route.
    client = _as_user(anon_client, user_auth_token)
    listing = client.get("/api/v1/providers")
    assert listing.status_code == 200
    row = next(p for p in listing.json() if p["slug"] == "openai")
    assert row["status"] == "unavailable"
    assert row["status_message"] == "Outage — ETA 30 min."

    # Master switch off → consistent disabled state, audited as a toggle.
    off = admin_client.put(
        "/api/v1/admin/providers/openai", json={"is_enabled": False}
    )
    assert off.status_code == 200
    assert off.json()["status"] == "disabled"
    assert off.json()["is_enabled"] is False
    assert len(await _audit_rows(test_db, "admin.provider_status_changed")) == 1

    # Master switch back on auto-restores availability (§9.1 consistency).
    on = admin_client.put(
        "/api/v1/admin/providers/openai", json={"is_enabled": True}
    )
    assert on.status_code == 200
    assert on.json()["status"] == "available"
    assert on.json()["is_enabled"] is True

    toggled = await _audit_rows(test_db, "admin.provider_toggled")
    assert len(toggled) == 2
    assert toggled[1].details["changes"] == {
        "status": "available",
        "is_enabled": True,
    }


async def test_admin_key_policy_change_audited(
    admin_client, test_db
):
    await _seed_provider(test_db)
    response = admin_client.put(
        "/api/v1/admin/providers/openai", json={"allow_key_addition": False}
    )
    assert response.status_code == 200
    assert response.json()["allow_key_addition"] is False

    rows = await _audit_rows(test_db, "admin.provider_keypolicy_changed")
    assert len(rows) == 1
    assert rows[0].details["changes"] == {"allow_key_addition": False}


# ---------------------------------------------------------------------------
# F2 — legacy user-namespace provider mutations must be audited + throttled
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Keep the shared per-IP limiter from bleeding across tests."""
    limiter.reset()
    yield
    limiter.reset()


async def test_legacy_provider_update_is_audited(admin_client, test_db):
    await _seed_provider(test_db)

    response = admin_client.put(
        "/api/v1/providers/openai", json={"display_name": "Renamed"}
    )
    assert response.status_code == 200, response.text

    rows = await _audit_rows(test_db, "admin.provider_status_changed")
    assert len(rows) == 1
    assert rows[0].details["changes"] == {"display_name": "Renamed"}
    assert rows[0].details["route"] == "legacy"
    assert rows[0].actor_id == "testadmin"


async def test_legacy_provider_toggle_is_audited(admin_client, test_db):
    await _seed_provider(test_db)

    response = admin_client.post(
        "/api/v1/providers/openai/toggle", json={"is_enabled": False}
    )
    assert response.status_code == 200, response.text

    rows = await _audit_rows(test_db, "admin.provider_toggled")
    assert len(rows) == 1
    assert rows[0].details["changes"] == {"is_enabled": False}
    assert rows[0].details["route"] == "legacy"


async def test_legacy_provider_sync_models_is_audited(
    admin_client, test_db, monkeypatch
):
    await _seed_provider(test_db)

    from app.api.v1.endpoints.providers import discovery_engine

    async def _fake_sync(db, slug, force=False):
        return []

    monkeypatch.setattr(discovery_engine, "sync_provider_models", _fake_sync)

    response = admin_client.post("/api/v1/providers/openai/sync-models")
    assert response.status_code == 200, response.text

    rows = await _audit_rows(test_db, "admin.provider_models_synced")
    assert len(rows) == 1
    assert rows[0].details["count"] == 0
    assert rows[0].details["route"] == "legacy"


async def test_legacy_provider_mutation_by_non_admin_writes_no_audit(
    anon_client, user_auth_token, test_db
):
    anon_client.cookies.set(SESSION_COOKIE_NAME, user_auth_token)
    response = anon_client.post(
        "/api/v1/providers/openai/toggle", json={"is_enabled": False}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin privileges required"
    assert await _audit_rows(test_db, "admin.provider_toggled") == []


async def test_user_provider_listing_hides_internal_wiring(client, test_db):
    """F3: user-authenticated GET /providers must not expose operator config."""
    provider = ProviderRegistry(
        name="openai",
        display_name="OpenAI",
        slug="openai",
        litellm_provider="openai",
        default_model="gpt-4o-mini",
        base_url_template="https://internal.example/v1",
        extra_config={"region": "internal-only"},
    )
    test_db.add(provider)
    await test_db.commit()

    response = client.get("/api/v1/providers")
    assert response.status_code == 200, response.text
    row = next(p for p in response.json() if p["slug"] == "openai")
    assert "base_url_template" not in row
    assert "extra_config" not in row
    assert row["default_model"] == "gpt-4o-mini"

    detail = client.get("/api/v1/providers/openai")
    assert detail.status_code == 200, detail.text
    assert "base_url_template" not in detail.json()
    assert "extra_config" not in detail.json()
