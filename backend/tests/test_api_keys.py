import pytest
import uuid
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.api_key import ApiKey
from app.core.security import encryption_service

@pytest.mark.asyncio
async def test_create_api_key(client: TestClient, test_db: AsyncSession):
    response = client.post(
        "/api/v1/api-keys",
        json={
            "provider": "openai",
            "label": "My OpenAI Key",
            "api_key": "sk-1234567890abcdef1234567890abcdef",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["provider"] == "openai"
    assert data["label"] == "My OpenAI Key"
    assert data["masked_key"] == "sk-1...cdef"
    assert "api_key" not in data

    # Verify storage in DB is encrypted
    key_id = uuid.UUID(data["id"])
    result = await test_db.execute(select(ApiKey).where(ApiKey.id == key_id))
    db_key = result.scalars().first()
    assert db_key is not None
    assert db_key.encrypted_key != "sk-1234567890abcdef1234567890abcdef"
    
    # Decrypt and verify
    decrypted = encryption_service.decrypt(db_key.encrypted_key)
    assert decrypted == "sk-1234567890abcdef1234567890abcdef"

@pytest.mark.asyncio
async def test_list_api_keys(client: TestClient, test_db: AsyncSession, mock_user):
    # Add a key directly to DB
    encrypted = encryption_service.encrypt("gemi-mysecretkeyval-999")
    key = ApiKey(
        user_id=mock_user.id,
        provider="gemini",
        label="Gemini Key",
        encrypted_key=encrypted,
        is_valid=True,
    )
    test_db.add(key)
    await test_db.commit()

    response = client.get("/api/v1/api-keys")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["provider"] == "gemini"
    assert data[0]["label"] == "Gemini Key"
    assert data[0]["masked_key"] == "gemi...-999"

@pytest.mark.asyncio
async def test_update_api_key(client: TestClient, test_db: AsyncSession, mock_user):
    encrypted = encryption_service.encrypt("oldkey")
    key = ApiKey(
        user_id=mock_user.id,
        provider="groq",
        label="Groq Key",
        encrypted_key=encrypted,
        is_valid=True,
    )
    test_db.add(key)
    await test_db.commit()

    # Update label and key value
    response = client.put(
        f"/api/v1/api-keys/{key.id}",
        json={
            "label": "Groq Updated",
            "api_key": "newgroqkey12345",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "Groq Updated"
    assert data["masked_key"] == "newg...2345"

    # Verify updated encryption in DB
    await test_db.refresh(key)
    decrypted = encryption_service.decrypt(key.encrypted_key)
    assert decrypted == "newgroqkey12345"

@pytest.mark.asyncio
async def test_delete_api_key(client: TestClient, test_db: AsyncSession, mock_user):
    encrypted = encryption_service.encrypt("testkey")
    key = ApiKey(
        user_id=mock_user.id,
        provider="deepseek",
        label="Deepseek Key",
        encrypted_key=encrypted,
        is_valid=True,
    )
    test_db.add(key)
    await test_db.commit()

    response = client.delete(f"/api/v1/api-keys/{key.id}")
    assert response.status_code == 204

    # Verify deleted from DB
    result = await test_db.execute(select(ApiKey).where(ApiKey.id == key.id))
    db_key = result.scalars().first()
    assert db_key is None

@pytest.mark.asyncio
@patch("app.api.v1.endpoints.api_keys.acompletion")
async def test_test_api_key_valid(mock_acompletion, client: TestClient, test_db: AsyncSession, mock_user):
    # Setup mock acompletion success
    mock_acompletion.return_value = AsyncMock()

    encrypted = encryption_service.encrypt("sk-valid")
    key = ApiKey(
        user_id=mock_user.id,
        provider="openai",
        label="OpenAI Key Test",
        encrypted_key=encrypted,
        is_valid=False,
    )
    test_db.add(key)
    await test_db.commit()

    response = client.post(f"/api/v1/api-keys/{key.id}/test")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    
    # Check key is marked valid in DB
    await test_db.refresh(key)
    assert key.is_valid is True

@pytest.mark.asyncio
@patch("app.api.v1.endpoints.api_keys.acompletion")
async def test_test_api_key_invalid(mock_acompletion, client: TestClient, test_db: AsyncSession, mock_user):
    # Setup mock acompletion error
    mock_acompletion.side_effect = Exception("Invalid API Key credentials")

    encrypted = encryption_service.encrypt("sk-invalid")
    key = ApiKey(
        user_id=mock_user.id,
        provider="openai",
        label="OpenAI Key Test",
        encrypted_key=encrypted,
        is_valid=True,
    )
    test_db.add(key)
    await test_db.commit()

    response = client.post(f"/api/v1/api-keys/{key.id}/test")
    assert response.status_code == 400
    data = response.json()
    assert "Connectivity test failed" in data["detail"]
    
    # Check key is marked invalid in DB
    await test_db.refresh(key)
    assert key.is_valid is False
