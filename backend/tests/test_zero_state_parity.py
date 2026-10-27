"""B23 zero-state parity (merge gate).

On a fresh database with default values (all providers enabled with
`status='available'`, all credentials enabled+valid, nothing blocked),
every touched surface must behave exactly like the pre-phase-4 baseline:

- `resolve_provider_config` returns the same MODE 1 / MODE 2 / MODE 3
  tuples;
- `model_router.route()` returns the identical provider set;
- `build_available_providers_for_user` returns the same discovery list;
- user routes keep their status codes: `GET /providers` 200,
  `PUT /routing/preferences` 200, `PATCH /repositories/{id}/config` 200,
  `POST /api-keys` 201.
"""

from sqlalchemy import select

from app.core.auth import SESSION_COOKIE_NAME
from app.core.security import encryption_service
from app.github.shared import (
    build_available_providers_for_user,
    resolve_provider_config,
)
from app.models.api_key import ApiKey
from app.models.github import Installation, Repository
from app.models.provider import ProviderRegistry
from app.services.model_router import model_router

RAW_KEY = "sk-parity-openai-123456"


async def _seed_zero_state(db, user) -> tuple[ProviderRegistry, ApiKey, Repository]:
    provider = ProviderRegistry(
        name="openai",
        display_name="OpenAI",
        slug="openai",
        litellm_provider="openai",
        default_model="gpt-4o-mini",
        priority=1,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    key = ApiKey(
        user_id=user.id,
        provider="openai",
        label="Primary",
        encrypted_key=encryption_service.encrypt(RAW_KEY),
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    installation = Installation(
        installation_id=99002,
        account_id=4243,
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
        github_id=88002,
        name="parity",
        full_name="acct/parity",
        installation_id=installation.id,
        reviews_enabled=True,
        settings={},
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)

    assert provider.status == "available"
    assert key.is_enabled is True and key.is_valid is True
    assert repo.settings == {}
    return provider, key, repo


async def test_zero_state_defaults_are_available(test_db, mock_user):
    provider, key, _repo = await _seed_zero_state(test_db, mock_user)
    assert provider.status == "available"
    assert provider.is_enabled is True
    assert provider.allow_key_addition is True


async def test_zero_state_resolve_provider_config_parity(test_db, mock_user):
    _provider, key, repo = await _seed_zero_state(test_db, mock_user)

    # MODE 3 — nothing configured.
    assert await resolve_provider_config(test_db, mock_user.id, None) == (
        None,
        None,
        None,
        "none",
    )

    # MODE 2 — user routing preference.
    mock_user.settings = {
        "model_routing": {
            "code_review": {"provider": "openai", "model": "gpt-4o-mini"}
        }
    }
    test_db.add(mock_user)
    await test_db.commit()
    assert await resolve_provider_config(test_db, mock_user.id, None) == (
        "openai",
        "gpt-4o-mini",
        str(key.id),
        "user_routing",
    )

    # MODE 1 — repo mapping wins.
    repo.settings = {
        "assigned_provider": "openai",
        "assigned_model": "gpt-4o-mini",
        "assigned_key_id": str(key.id),
    }
    test_db.add(repo)
    await test_db.commit()
    assert await resolve_provider_config(test_db, mock_user.id, repo) == (
        "openai",
        "gpt-4o-mini",
        str(key.id),
        "repo_config",
    )


async def test_zero_state_model_router_parity(test_db, mock_user):
    _provider, key, _repo = await _seed_zero_state(test_db, mock_user)

    routes = await model_router.route(test_db, mock_user.id, "code_review")
    assert len(routes) == 1
    route = routes[0]
    assert route.provider == "openai"
    assert route.model == "gpt-4o-mini"
    assert route.litellm_model == "openai/gpt-4o-mini"
    assert route.api_key_id == str(key.id)


async def test_zero_state_available_providers_parity(test_db, mock_user):
    _provider, key, _repo = await _seed_zero_state(test_db, mock_user)
    available = await build_available_providers_for_user(
        test_db, mock_user.id
    )
    assert available == [("openai", "gpt-4o-mini", str(key.id))]


async def test_zero_state_user_routes_parity(
    test_db, anon_client, user_auth_token, mock_user, monkeypatch
):
    _provider, _key, repo = await _seed_zero_state(test_db, mock_user)
    anon_client.cookies.set(SESSION_COOKIE_NAME, user_auth_token)
    monkeypatch.setattr(
        "app.services.model_discovery.warm_model_cache",
        lambda *args, **kwargs: None,
    )

    listing = anon_client.get("/api/v1/providers")
    assert listing.status_code == 200
    rows = listing.json()
    assert [row["slug"] for row in rows] == ["openai"]
    assert rows[0]["status"] == "available"

    routing = anon_client.put(
        "/api/v1/routing/preferences",
        json={
            "routing": {
                "code_review": {"provider": "openai", "model": "gpt-4o-mini"}
            }
        },
    )
    assert routing.status_code == 200

    config = anon_client.patch(
        f"/api/v1/repositories/{repo.id}/config",
        json={"assigned_provider": "openai", "assigned_model": "gpt-4o-mini"},
    )
    assert config.status_code == 200, config.text

    created = anon_client.post(
        "/api/v1/api-keys",
        json={"provider": "openai", "label": "Parity", "api_key": RAW_KEY},
    )
    assert created.status_code == 201, created.text

    keys = (
        await test_db.execute(select(ApiKey.id).where(ApiKey.user_id == mock_user.id))
    ).scalars().all()
    assert len(keys) == 2
