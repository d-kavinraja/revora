import pytest

from app.services.platform_settings import platform_settings_service


@pytest.fixture(autouse=True)
def _reset_limiter():
    from app.middleware.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


async def test_usage_analytics_default_enabled(anon_client):
    r = anon_client.get("/api/v1/platform/features")
    assert r.status_code == 200
    assert r.json()["usage"]["status"] == "enabled"
    assert r.json()["analytics"]["status"] == "enabled"


async def test_admin_can_disable_and_reenable(admin_client):
    r = admin_client.get("/api/v1/admin/usage-analytics")
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    version = r.json()["version"]

    r = admin_client.put(
        "/api/v1/admin/usage-analytics",
        json={"enabled": False, "version": version},
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = admin_client.get("/api/v1/platform/usage-analytics")
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = admin_client.get("/api/v1/admin/usage-analytics")
    version = r.json()["version"]
    r = admin_client.put(
        "/api/v1/admin/usage-analytics",
        json={"enabled": True, "version": version},
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is True


async def test_non_admin_cannot_change(client):
    r = client.put("/api/v1/admin/usage-analytics", json={"enabled": False})
    assert r.status_code in (401, 403)


async def test_service_resolver_reflects_admin_override(test_db):
    state, prior, conflict = await platform_settings_service.set_usage_analytics(
        test_db, enabled=False, admin_id=None
    )
    assert conflict is None
    await test_db.commit()
    assert await platform_settings_service.is_usage_analytics_enabled(test_db) is False

    state, prior, conflict = await platform_settings_service.set_usage_analytics(
        test_db, enabled=True, admin_id=None
    )
    await test_db.commit()
    assert await platform_settings_service.is_usage_analytics_enabled(test_db) is True
