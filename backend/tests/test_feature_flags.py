"""Phase 6 suite: feature flags, Model Lab availability and API-key policy
(§11, B27) plus the admin flag/override surfaces (§18).

Covers:
- default tolerance (missing rows ⇒ enabled — zero-state parity, B23);
- `require_feature` blocking matrix per §11.1 (model_lab, mouthmap,
  api_keys_add, routing_mapping, review_initiation) with exact
  `503 {"code": "feature_disabled", "message": ...}` payloads;
- admin-role user bypass; independence (B27: one flip leaves every other
  endpoint's status code unchanged);
- `usage`/`analytics` flag honoring with the env as master;
- admin `GET/PUT /admin/features` (+ audit, 404/400) and
  `GET/PUT /admin/models/overrides` (+ audit, clear-on-available, 404/400);
- per-model override enforcement in model listing, routing and explicit
  LLM execution (per-model only — provider stays usable).
"""

import uuid

import pytest
from sqlalchemy import select

from app.api.v1.endpoints import usage as usage_module
from app.core.config import settings
from app.core.security import encryption_service
from app.middleware.rate_limit import limiter
from app.models.api_key import ApiKey
from app.models.audit import AuditLog
from app.models.platform import FEATURE_FLAG_KEYS, FeatureFlag
from app.models.provider import ProviderRegistry
from app.services.model_discovery import model_discovery_engine
from app.services.model_overrides import model_overrides_service
from app.services.model_router import model_router
from app.services.platform_settings import platform_settings_service

RAW_KEY = "sk-flag-openai-123456"


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Keep the per-IP limiter from bleeding across tests (as elsewhere)."""
    limiter.reset()
    yield
    limiter.reset()


async def _set_flag(db, key: str, status: str, message: str | None = None):
    new_state, _prior = await platform_settings_service.set_flag(
        db, key, status=status, message=message
    )
    await db.commit()
    return new_state


async def _seed_provider(
    db,
    *,
    name: str = "openai",
    default_model: str = "gpt-4o-mini",
    status: str = "available",
    is_enabled: bool = True,
) -> ProviderRegistry:
    provider = ProviderRegistry(
        name=name,
        display_name=name.title(),
        slug=name,
        litellm_provider=name,
        default_model=default_model,
        priority=1,
        status=status,
        is_enabled=is_enabled,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


async def _seed_key(db, user, *, provider: str = "openai") -> ApiKey:
    key = ApiKey(
        user_id=user.id,
        provider=provider,
        label="Primary",
        encrypted_key=encryption_service.encrypt(RAW_KEY),
        is_valid=True,
        is_enabled=True,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


# ---------------------------------------------------------------------------
# Default tolerance + model_lab gating (B27)
# ---------------------------------------------------------------------------


def test_missing_flag_rows_mean_enabled(client):
    """Zero-state parity: no `feature_flags` rows ⇒ gated routes stay open."""
    assert client.get("/api/v1/models").status_code == 200
    assert client.get("/api/v1/api-keys").status_code == 200
    assert client.get("/api/v1/routing/preferences").status_code == 200


async def test_seeded_enabled_flags_preserve_behavior(client, test_db):
    """Migration-seeded `enabled` rows behave exactly like missing rows."""
    for key in FEATURE_FLAG_KEYS:
        test_db.add(FeatureFlag(key=key, status="enabled"))
    await test_db.commit()
    assert client.get("/api/v1/models").status_code == 200
    assert client.get("/api/v1/api-keys").status_code == 200
    assert client.get("/api/v1/routing/preferences").status_code == 200


async def test_model_lab_flag_blocks_models_and_execute(client, test_db):
    await _set_flag(test_db, "model_lab", "disabled", "Lab offline")

    listing = client.get("/api/v1/models")
    assert listing.status_code == 503
    assert listing.json() == {
        "code": "feature_disabled",
        "message": "Lab offline",
    }

    execute = client.post(
        "/api/v1/llm/execute",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert execute.status_code == 503
    assert execute.json()["code"] == "feature_disabled"


async def test_flag_message_falls_back_when_unset(client, test_db):
    await _set_flag(test_db, "model_lab", "disabled", None)
    body = client.get("/api/v1/models").json()
    assert body["code"] == "feature_disabled"
    assert "Model Lab" in body["message"]


async def test_admin_role_user_bypasses_flags(client, test_db, mock_user):
    await _set_flag(test_db, "model_lab", "disabled", "Lab offline")
    mock_user.role = "admin"
    try:
        assert client.get("/api/v1/models").status_code == 200
    finally:
        mock_user.role = "user"
    assert client.get("/api/v1/models").status_code == 503


async def test_b27_one_flip_leaves_other_endpoints_unchanged(client, test_db):
    """Independence: only model_lab-gated routes change status code."""
    baseline = {
        "/api/v1/api-keys": client.get("/api/v1/api-keys").status_code,
        "/api/v1/routing/preferences": client.get(
            "/api/v1/routing/preferences"
        ).status_code,
        "/api/v1/providers": client.get("/api/v1/providers").status_code,
    }
    await _set_flag(test_db, "model_lab", "disabled", "Lab offline")
    assert client.get("/api/v1/models").status_code == 503
    for path, code in baseline.items():
        assert client.get(path).status_code == code, path


# ---------------------------------------------------------------------------
# mouthmap
# ---------------------------------------------------------------------------

MOUTHMAP_GET_ROUTES = [
    "/api/v1/mouthmap/config",
    "/api/v1/mouthmap/health",
    "/api/v1/mouthmap/dataset",
    "/api/v1/mouthmap/history",
    "/api/v1/mouthmap/dataset/some-video/stream",
]


@pytest.mark.parametrize("path", MOUTHMAP_GET_ROUTES)
async def test_mouthmap_flag_blocks_all_get_routes(client, test_db, path):
    await _set_flag(test_db, "mouthmap", "disabled", "MouthMap offline")
    response = client.get(path)
    assert response.status_code == 503, path
    assert response.json()["code"] == "feature_disabled"


async def test_mouthmap_flag_blocks_inference(client, test_db):
    await _set_flag(test_db, "mouthmap", "disabled", "MouthMap offline")
    response = client.post(
        "/api/v1/mouthmap/inference",
        files={"video": ("v.mp4", b"payload", "video/mp4")},
        data={"source": "upload"},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "feature_disabled"


async def test_mouthmap_enabled_route_is_not_blocked(client, test_db):
    """No flag row ⇒ enabled ⇒ the flag layer never 503s mouthmap."""
    await _set_flag(test_db, "mouthmap", "enabled", None)
    assert client.get("/api/v1/mouthmap/config").status_code != 503


# ---------------------------------------------------------------------------
# api_keys_add (reads stay, per §11.1)
# ---------------------------------------------------------------------------

KEY_ID = uuid.uuid4()


async def test_api_keys_add_flag_blocks_mutations_keeps_reads(client, test_db):
    await _set_flag(test_db, "api_keys_add", "disabled", "Adding keys is paused")

    create = client.post(
        "/api/v1/api-keys",
        json={"provider": "openai", "label": "x", "api_key": RAW_KEY},
    )
    assert create.status_code == 503
    assert create.json()["code"] == "feature_disabled"

    update = client.put(f"/api/v1/api-keys/{KEY_ID}", json={"label": "y"})
    assert update.status_code == 503

    rotate = client.post(
        f"/api/v1/api-keys/{KEY_ID}/rotate", json={"api_key": RAW_KEY}
    )
    assert rotate.status_code == 503

    assert client.get("/api/v1/api-keys").status_code == 200
    # Test stays available (§10: existing keys stay testable).
    test_call = client.post(f"/api/v1/api-keys/{KEY_ID}/test")
    assert test_call.status_code != 503


# ---------------------------------------------------------------------------
# routing_mapping
# ---------------------------------------------------------------------------


async def test_routing_mapping_flag_blocks_writes_keeps_reads(client, test_db):
    await _set_flag(test_db, "routing_mapping", "disabled", "Mapping is frozen")

    put = client.put(
        "/api/v1/routing/preferences",
        json={"routing": {"code_review": {"provider": "openai"}}},
    )
    assert put.status_code == 503
    assert put.json()["code"] == "feature_disabled"

    patch = client.patch(
        f"/api/v1/repositories/{uuid.uuid4()}/config",
        json={"assigned_provider": "openai"},
    )
    assert patch.status_code == 503

    assert client.get("/api/v1/routing/preferences").status_code == 200
    assert client.get("/api/v1/routing/routes").status_code == 200


# ---------------------------------------------------------------------------
# review_initiation
# ---------------------------------------------------------------------------

LIFECYCLE_ROUTES = [
    "rerun",
    "retry",
    "restart",
]


@pytest.mark.parametrize("action", LIFECYCLE_ROUTES)
async def test_review_initiation_flag_blocks_lifecycle(client, test_db, action):
    await _set_flag(
        test_db, "review_initiation", "disabled", "New reviews are paused"
    )
    response = client.post(f"/api/v1/reviews/{uuid.uuid4()}/{action}")
    assert response.status_code == 503, action
    assert response.json()["code"] == "feature_disabled"


async def test_cancel_stays_available_when_review_initiation_disabled(
    client, test_db
):
    """Cancel is explicitly not gated by `review_initiation` (§11.1)."""
    await _set_flag(test_db, "review_initiation", "disabled", "Paused")
    response = client.post(f"/api/v1/reviews/{uuid.uuid4()}/cancel")
    assert response.status_code != 503
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# usage / analytics (env remains master)
# ---------------------------------------------------------------------------


async def test_usage_flag_honored_while_env_enabled(
    client, test_db, monkeypatch
):
    monkeypatch.setattr(settings, "USAGE_ANALYTICS_ENABLED", True)
    await _set_flag(test_db, "usage", "disabled", "Usage is paused")

    blocked = client.get("/api/v1/platform-usage/summary")
    assert blocked.status_code == 503
    assert blocked.json() == {
        "code": "feature_disabled",
        "message": "Usage is paused",
    }

    await _set_flag(test_db, "usage", "enabled", None)
    assert client.get("/api/v1/platform-usage/summary").status_code == 200


async def test_usage_env_gate_contract_unchanged(client, test_db, monkeypatch):
    """Env off ⇒ the pre-phase-6 detail payload/message, even with flag on."""
    monkeypatch.setattr(settings, "USAGE_ANALYTICS_ENABLED", False)
    response = client.get("/api/v1/platform-usage/summary")
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "disabled"


async def test_analytics_flag_honored_while_env_enabled(
    client, test_db, monkeypatch
):
    monkeypatch.setattr(settings, "USAGE_ANALYTICS_ENABLED", True)
    await _set_flag(test_db, "analytics", "disabled", "Analytics is paused")

    blocked = client.get("/api/v1/platform-analytics/requests")
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "feature_disabled"

    await _set_flag(test_db, "analytics", "enabled", None)
    assert client.get("/api/v1/platform-analytics/requests").status_code == 200


async def test_usage_env_disabled_is_master_over_enabled_flag(
    client, test_db, monkeypatch
):
    monkeypatch.setattr(settings, "USAGE_ANALYTICS_ENABLED", False)
    await _set_flag(test_db, "usage", "enabled", None)
    response = client.get("/api/v1/platform-usage/summary")
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "disabled"
    # Sanity: the module used by the route is the patched settings object.
    assert usage_module.settings.USAGE_ANALYTICS_ENABLED is False


# ---------------------------------------------------------------------------
# Public features surface
# ---------------------------------------------------------------------------


def test_public_features_default_shape(anon_client):
    response = anon_client.get("/api/v1/platform/features")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == set(FEATURE_FLAG_KEYS)
    for key in FEATURE_FLAG_KEYS:
        assert body[key]["status"] == "enabled"
        assert body[key]["message"] is None


async def test_public_features_reflect_admin_changes(admin_client, anon_client):
    update = admin_client.put(
        "/api/v1/admin/features/mouthmap",
        json={"status": "coming_soon", "message": "Almost there"},
    )
    assert update.status_code == 200, update.text

    body = anon_client.get("/api/v1/platform/features").json()
    assert body["mouthmap"] == {"status": "coming_soon", "message": "Almost there"}

    public_status = anon_client.get("/api/v1/platform/status").json()
    assert public_status["features"]["mouthmap"] == "coming_soon"


# ---------------------------------------------------------------------------
# Admin feature flags
# ---------------------------------------------------------------------------


async def test_admin_features_list_covers_canonical_keys(admin_client):
    response = admin_client.get("/api/v1/admin/features")
    assert response.status_code == 200
    rows = response.json()
    assert [row["key"] for row in rows] == list(FEATURE_FLAG_KEYS)
    assert all(row["status"] == "enabled" for row in rows)
    assert all(row["message"] is None for row in rows)


async def test_admin_feature_flip_end_to_end(
    admin_client, client, test_db, anon_client
):
    update = admin_client.put(
        "/api/v1/admin/features/model_lab",
        json={"status": "disabled", "message": "Lab offline"},
    )
    assert update.status_code == 200, update.text
    assert update.json()["status"] == "disabled"

    # Persisted row + actor.
    row = (
        await test_db.execute(
            select(FeatureFlag).where(FeatureFlag.key == "model_lab")
        )
    ).scalars().first()
    assert row is not None and row.status == "disabled"
    assert row.updated_by is not None

    # Audit row (§16) with admin actor.
    audit = (
        await test_db.execute(
            select(AuditLog).where(
                AuditLog.action == "admin.feature_flag_changed"
            )
        )
    ).scalars().first()
    assert audit is not None
    assert audit.actor_type == "admin"
    assert audit.entity_id == "model_lab"

    # Live flip with no redeploy (write path invalidates the TTL cache).
    blocked = client.get("/api/v1/models")
    assert blocked.status_code == 503
    assert blocked.json()["message"] == "Lab offline"

    # Re-enable restores behavior immediately; stored data untouched.
    restore = admin_client.put(
        "/api/v1/admin/features/model_lab",
        json={"status": "enabled", "message": None},
    )
    assert restore.status_code == 200
    assert client.get("/api/v1/models").status_code == 200


async def test_admin_feature_update_validation(admin_client):
    unknown = admin_client.put(
        "/api/v1/admin/features/not_a_flag", json={"status": "disabled"}
    )
    assert unknown.status_code == 404

    invalid = admin_client.put(
        "/api/v1/admin/features/model_lab", json={"status": "banana"}
    )
    assert invalid.status_code == 400


# ---------------------------------------------------------------------------
# Admin model overrides
# ---------------------------------------------------------------------------


async def test_admin_model_overrides_crud_and_audit(admin_client, test_db):
    await _seed_provider(test_db)

    set_response = admin_client.put(
        "/api/v1/admin/models/overrides",
        json={
            "provider_slug": "openai",
            "model_id": "gpt-4o-mini",
            "status": "disabled",
            "message": "Deprecated for now",
        },
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json()["status"] == "disabled"

    listed = admin_client.get("/api/v1/admin/models/overrides")
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "provider_slug": "openai",
            "model_id": "gpt-4o-mini",
            "status": "disabled",
            "message": "Deprecated for now",
        }
    ]

    audit = (
        await test_db.execute(
            select(AuditLog).where(
                AuditLog.action == "admin.model_override_set"
            )
        )
    ).scalars().first()
    assert audit is not None and audit.actor_type == "admin"

    # `available` clears the override (restores with no user action).
    cleared = admin_client.put(
        "/api/v1/admin/models/overrides",
        json={
            "provider_slug": "openai",
            "model_id": "gpt-4o-mini",
            "status": "available",
        },
    )
    assert cleared.status_code == 200
    assert admin_client.get("/api/v1/admin/models/overrides").json() == []
    clear_audit = (
        await test_db.execute(
            select(AuditLog).where(
                AuditLog.action == "admin.model_override_cleared"
            )
        )
    ).scalars().first()
    assert clear_audit is not None


async def test_admin_model_override_validation(admin_client, test_db):
    unknown = admin_client.put(
        "/api/v1/admin/models/overrides",
        json={
            "provider_slug": "ghost",
            "model_id": "m1",
            "status": "disabled",
        },
    )
    assert unknown.status_code == 404

    await _seed_provider(test_db)
    invalid = admin_client.put(
        "/api/v1/admin/models/overrides",
        json={
            "provider_slug": "openai",
            "model_id": "gpt-4o-mini",
            "status": "banana",
        },
    )
    assert invalid.status_code == 400


# ---------------------------------------------------------------------------
# Per-model override enforcement (per-model only)
# ---------------------------------------------------------------------------


async def test_model_override_filters_listing_routing_and_execution(
    client, test_db, mock_user, monkeypatch
):
    await _seed_provider(test_db)
    await _seed_key(test_db, mock_user)

    async def fake_models(provider_name, raw_key):
        return ["gpt-4o-mini", "gpt-4o"]

    monkeypatch.setattr(model_discovery_engine, "get_available_models", fake_models)

    # Baseline (no overrides): both models listed, routing works.
    baseline = client.get("/api/v1/models")
    assert baseline.status_code == 200
    assert baseline.json()["openai"] == ["gpt-4o-mini", "gpt-4o"]
    routes = await model_router.route(test_db, mock_user.id, "code_review")
    assert len(routes) == 1

    _row, action = await model_overrides_service.apply(
        test_db,
        provider_slug="openai",
        model_id="gpt-4o-mini",
        status="disabled",
        message="Off",
    )
    assert action == "set"
    await test_db.commit()

    # Listing excludes only the disabled model.
    filtered = client.get("/api/v1/models")
    assert filtered.json()["openai"] == ["gpt-4o"]

    # Routing skips the disabled default model (provider stays configured —
    # no substitution is invented: the route simply disappears).
    assert await model_router.route(test_db, mock_user.id, "code_review") == []

    # Explicit execution of the disabled model is refused before any
    # provider call (400, not a provider error).
    execute = client.post(
        "/api/v1/llm/execute",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "preferred_provider": "openai",
            "preferred_model": "gpt-4o-mini",
        },
    )
    assert execute.status_code == 400
    assert "unavailable" in execute.json()["detail"].lower()

    # Clearing restores everything with no user action.
    _row, action = await model_overrides_service.apply(
        test_db,
        provider_slug="openai",
        model_id="gpt-4o-mini",
        status="available",
    )
    assert action == "cleared"
    await test_db.commit()
    assert client.get("/api/v1/models").json()["openai"] == [
        "gpt-4o-mini",
        "gpt-4o",
    ]
    assert len(await model_router.route(test_db, mock_user.id, "code_review")) == 1
