# MANDATORY INTEGRITY WARNING:
# DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results,
# create dummy/facade implementations, or circumvent the intended task. A Forensic
# Auditor will independently verify your work. Integrity violations WILL be detected
# and your work WILL be rejected.

import pytest
import uuid
from app.models.api_key import ApiKey
from app.core.security import encryption_service
from conftest import MOCK_USER_ID

def test_create_openai_key_success(client):
    # Tier 1 - Feature Coverage: Create OpenAI key
    payload = {
        "provider": "openai",
        "label": "My OpenAI Key",
        "api_key": "sk-proj-1234567890abcdef"
    }
    response = client.post("/api/v1/api-keys", json=payload)
    assert response.status_code == 201
    
    data = response.json()
    assert data["provider"] == "openai"
    assert data["label"] == "My OpenAI Key"
    assert data["masked_key"] == "sk-p...cdef"
    assert "api_key" not in data

def test_create_anthropic_key_success(client):
    # Tier 1 - Feature Coverage: Create Anthropic key
    payload = {
        "provider": "anthropic",
        "label": "My Claude Key",
        "api_key": "sk-ant-sid-1234567890"
    }
    response = client.post("/api/v1/api-keys", json=payload)
    assert response.status_code == 201
    
    data = response.json()
    assert data["provider"] == "anthropic"
    assert data["masked_key"] == "sk-a...67890"

def test_get_keys_list_returns_masked(client):
    # Tier 1 - Feature Coverage: List keys returns masked
    # Create two keys first
    client.post("/api/v1/api-keys", json={
        "provider": "openai", "label": "Key 1", "api_key": "sk-openai-key-value-1"
    })
    client.post("/api/v1/api-keys", json={
        "provider": "gemini", "label": "Key 2", "api_key": "gemini-key-value-2"
    })
    
    response = client.get("/api/v1/api-keys")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) >= 2
    for item in data:
        assert "api_key" not in item
        assert "encrypted_key" not in item
        assert "masked_key" in item
        assert "..." in item["masked_key"]

def test_update_key_label_success(client):
    # Tier 1 - Feature Coverage: Update key label
    create_res = client.post("/api/v1/api-keys", json={
        "provider": "openai", "label": "Old Label", "api_key": "sk-openai-key-value-1"
    })
    key_id = create_res.json()["id"]
    
    response = client.put(f"/api/v1/api-keys/{key_id}", json={
        "label": "New Label"
    })
    assert response.status_code == 200
    assert response.json()["label"] == "New Label"

def test_delete_key_success(client):
    # Tier 1 - Feature Coverage: Delete key
    create_res = client.post("/api/v1/api-keys", json={
        "provider": "openai", "label": "Delete Me", "api_key": "sk-openai-key-value-1"
    })
    key_id = create_res.json()["id"]
    
    response = client.delete(f"/api/v1/api-keys/{key_id}")
    assert response.status_code == 204
    
    # Verify not found
    get_res = client.get("/api/v1/api-keys")
    ids = [item["id"] for item in get_res.json()]
    assert key_id not in ids

def test_test_key_endpoint_returns_success(client):
    # Tier 1 - Feature Coverage: Test connection endpoint
    create_res = client.post("/api/v1/api-keys", json={
        "provider": "openai", "label": "Valid Key", "api_key": "sk-openai-key-value-1"
    })
    key_id = create_res.json()["id"]
    
    response = client.post(f"/api/v1/api-keys/{key_id}/test")
    assert response.status_code == 200
    assert response.json()["status"] == "success"

def test_create_key_invalid_provider(client):
    # Tier 2 - Boundary/Corner: Invalid provider validation
    payload = {
        "provider": "invalid-provider-name",
        "label": "My Key",
        "api_key": "sk-proj-1234567890abcdef"
    }
    response = client.post("/api/v1/api-keys", json=payload)
    assert response.status_code == 400

def test_create_openai_key_invalid_format(client):
    # Tier 2 - Boundary/Corner: OpenAI format validation check
    payload = {
        "provider": "openai",
        "label": "Invalid OpenAI Key",
        "api_key": "invalid-prefix-12345"
    }
    response = client.post("/api/v1/api-keys", json=payload)
    assert response.status_code == 422
    assert "OpenAI keys must start with sk-" in response.json()["detail"]

def test_create_anthropic_key_invalid_format(client):
    # Tier 2 - Boundary/Corner: Anthropic format validation check
    payload = {
        "provider": "anthropic",
        "label": "Invalid Anthropic Key",
        "api_key": "sk-invalid-prefix-12345"
    }
    response = client.post("/api/v1/api-keys", json=payload)
    assert response.status_code == 422
    assert "Anthropic keys must start with sk-ant-" in response.json()["detail"]

def test_update_key_with_unauthorized_user(client, monkeypatch):
    # Tier 2 - Boundary/Corner: Update key of another user
    create_res = client.post("/api/v1/api-keys", json={
        "provider": "openai", "label": "Owner Key", "api_key": "sk-openai-key-value-1"
    })
    key_id = create_res.json()["id"]
    
    # Change get_mock_current_user to return a user with a different ID
    from conftest import User
    async def fake_user(*args, **kwargs):
        return User(id=uuid.uuid4(), name="Other User", email="other@revora.ai")
    monkeypatch.setattr("conftest.get_mock_current_user", fake_user)
    
    response = client.put(f"/api/v1/api-keys/{key_id}", json={
        "label": "Hijacked"
    })
    assert response.status_code == 404

def test_delete_key_not_found(client):
    # Tier 2 - Boundary/Corner: Delete non-existent key
    random_id = uuid.uuid4()
    response = client.delete(f"/api/v1/api-keys/{random_id}")
    assert response.status_code == 404

def test_test_key_endpoint_connectivity_fail(client):
    # Tier 2 - Boundary/Corner: Test key failure connectivity response
    create_res = client.post("/api/v1/api-keys", json={
        "provider": "openai", "label": "Fail Key", "api_key": "sk-fail-openai-key-value"
    })
    key_id = create_res.json()["id"]
    
    response = client.post(f"/api/v1/api-keys/{key_id}/test")
    assert response.status_code == 400
    assert "Connectivity test failed" in response.json()["detail"]
