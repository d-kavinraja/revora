
import pytest

from app.models.github import Installation


@pytest.mark.asyncio
async def test_admin_installations_list_returns_rows(test_db, admin_client, mock_user):
    inst = Installation(
        installation_id=12345,
        account_id=999,
        account_login="test-org",
        account_type="Organization",
        user_id=mock_user.id,
        repository_selection="all",
        permissions={"pull_requests": "write"},
        events={},
        lifecycle_status="active",
    )
    test_db.add(inst)
    await test_db.commit()

    response = admin_client.get("/api/v1/admin/installations")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(item["installation_id"] == 12345 for item in data["items"])


def test_admin_installations_requires_admin(anon_client):
    response = anon_client.get("/api/v1/admin/installations")
    assert response.status_code == 401
