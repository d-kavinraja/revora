import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encryption_service
from app.models.api_key import ApiKey


@pytest.mark.asyncio
async def test_operation_enqueue_and_get(client: TestClient, test_db: AsyncSession, mock_user):
    encrypted = encryption_service.encrypt("sk-test-key-1234567890")
    key = ApiKey(user_id=mock_user.id, provider="openai", label="K", encrypted_key=encrypted, is_valid=True)
    test_db.add(key)
    await test_db.commit()

    response = client.post(f"/api/v1/api-keys/{key.id}/test")
    assert response.status_code == 202
    job = response.json()
    assert job["operation_type"] == "api_key_test"
    assert job["status"] in {"queued", "running", "completed"}

    fetched = client.get(f"/api/v1/operations/{job['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == job["id"]


@pytest.mark.asyncio
async def test_operation_cross_user_404(client: TestClient, test_db: AsyncSession, mock_user):
    job_id = uuid.uuid4()
    response = client.get(f"/api/v1/operations/{job_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_provider_health_check_enqueue(client: TestClient, test_db: AsyncSession, mock_user):
    encrypted = encryption_service.encrypt("sk-test-key-1234567890")
    key = ApiKey(user_id=mock_user.id, provider="openai", label="K", encrypted_key=encrypted, is_valid=True)
    test_db.add(key)
    await test_db.commit()

    response = client.post("/api/v1/health/providers/openai/check")
    assert response.status_code == 202
    assert response.json()["operation_type"] == "provider_health_check"


@pytest.mark.asyncio
async def test_operation_completes_and_persists(
    client: TestClient, test_db: AsyncSession, mock_user
):
    from unittest.mock import AsyncMock, patch

    encrypted = encryption_service.encrypt("sk-test-key-1234567890")
    key = ApiKey(user_id=mock_user.id, provider="openai", label="K", encrypted_key=encrypted, is_valid=False)
    test_db.add(key)
    await test_db.commit()
    await test_db.refresh(key)

    with patch(
        "app.services.model_discovery.model_discovery_engine.get_available_models",
        new=AsyncMock(return_value=[{"id": "gpt-4o"}]),
    ):
        response = client.post(f"/api/v1/api-keys/{key.id}/test")
        assert response.status_code == 202
        from tests.operation_helpers import job_items, run_operation_job_inline

        job = await run_operation_job_inline(client, test_db, response.json()["id"])

    assert job["status"] == "completed"
    assert job_items(job)[str(key.id)]["status"] == "success"
    await test_db.refresh(key)
    assert key.is_valid is True


@pytest.mark.asyncio
async def test_operation_dedupe_returns_same_active_job(
    client: TestClient, test_db: AsyncSession, mock_user
):
    encrypted = encryption_service.encrypt("sk-test-key-1234567890")
    key = ApiKey(user_id=mock_user.id, provider="openai", label="K", encrypted_key=encrypted, is_valid=True)
    test_db.add(key)
    await test_db.commit()
    await test_db.refresh(key)

    first = client.post(f"/api/v1/api-keys/{key.id}/test")
    second = client.post(f"/api/v1/api-keys/{key.id}/test")
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
