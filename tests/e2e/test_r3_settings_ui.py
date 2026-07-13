# MANDATORY INTEGRITY WARNING:
# DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results,
# create dummy/facade implementations, or circumvent the intended task. A Forensic
# Auditor will independently verify your work. Integrity violations WILL be detected
# and your work WILL be rejected.

import pytest

def test_settings_theme_config(client):
    # Tier 1 - Feature Coverage: Checking settings UI theme aesthetics config
    response = client.get("/api/v1/ui/settings/theme")
    assert response.status_code == 200
    data = response.json()
    assert data["theme"] == "dark"
    assert data["glassmorphic"] is True
    assert "indigo" in data["primary_color"].lower() or data["primary_color"] == "#6366f1"

def test_settings_form_validation_openai_valid(client):
    # Tier 1 - Feature Coverage: Valid OpenAI key input form validation
    payload = {
        "provider": "openai",
        "api_key": "sk-proj-valid-openai-key-value",
        "label": "My OpenAI Key"
    }
    response = client.post("/api/v1/ui/settings/validate-form", json=payload)
    assert response.status_code == 200
    assert response.json()["valid"] is True

def test_settings_form_validation_anthropic_valid(client):
    # Tier 1 - Feature Coverage: Valid Anthropic key input form validation
    payload = {
        "provider": "anthropic",
        "api_key": "sk-ant-valid-anthropic-key-value",
        "label": "My Anthropic Key"
    }
    response = client.post("/api/v1/ui/settings/validate-form", json=payload)
    assert response.status_code == 200
    assert response.json()["valid"] is True

def test_settings_form_validation_gemini_valid(client):
    # Tier 1 - Feature Coverage: Valid Gemini key input form validation
    payload = {
        "provider": "gemini",
        "api_key": "gemini-valid-gemini-key-value",
        "label": "My Gemini Key"
    }
    response = client.post("/api/v1/ui/settings/validate-form", json=payload)
    assert response.status_code == 200
    assert response.json()["valid"] is True

def test_settings_masked_keys_display_format(client):
    # Tier 1 - Feature Coverage: Masked key display format on Settings Page UI
    client.post("/api/v1/api-keys", json={
        "provider": "openai", "label": "UI Key 1", "api_key": "sk-openai-val-1"
    })
    
    response = client.get("/api/v1/api-keys")
    assert response.status_code == 200
    keys = response.json()
    assert len(keys) > 0
    # Verifies standard masking format sk-o...val-1 (4 characters prefix, 3 dots, 4 characters suffix)
    masked = keys[0]["masked_key"]
    assert masked.startswith("sk-o")
    assert masked.endswith("al-1")
    assert "..." in masked

def test_settings_key_testing_success(client):
    # Tier 1 - Feature Coverage: Test key connection success triggers success UI status
    create_res = client.post("/api/v1/api-keys", json={
        "provider": "openai", "label": "UI Test Key", "api_key": "sk-openai-key-value-1"
    })
    key_id = create_res.json()["id"]
    
    response = client.post(f"/api/v1/api-keys/{key_id}/test")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "verified" in data["message"].lower()

def test_settings_form_validation_missing_fields(client):
    # Tier 2 - Boundary/Corner: Missing required form fields
    payload = {
        "provider": "openai",
        "label": "Missing API Key"
    }
    response = client.post("/api/v1/ui/settings/validate-form", json=payload)
    assert response.status_code == 400

def test_settings_form_validation_openai_invalid_prefix(client):
    # Tier 2 - Boundary/Corner: OpenAI invalid prefix error handling payload
    payload = {
        "provider": "openai",
        "api_key": "invalid-prefix-openai",
        "label": "OpenAI Key"
    }
    response = client.post("/api/v1/ui/settings/validate-form", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert "sk-" in data["errors"]["api_key"]

def test_settings_form_validation_anthropic_invalid_prefix(client):
    # Tier 2 - Boundary/Corner: Anthropic invalid prefix error handling payload
    payload = {
        "provider": "anthropic",
        "api_key": "sk-invalid-prefix-anthropic",
        "label": "Anthropic Key"
    }
    response = client.post("/api/v1/ui/settings/validate-form", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert "sk-ant-" in data["errors"]["api_key"]

def test_settings_form_validation_key_too_short(client):
    # Tier 2 - Boundary/Corner: Key too short validation check
    payload = {
        "provider": "gemini",
        "api_key": "short",
        "label": "Gemini Key"
    }
    response = client.post("/api/v1/ui/settings/validate-form", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert "too short" in data["errors"]["api_key"].lower()

def test_settings_key_testing_failure_error_payload(client):
    # Tier 2 - Boundary/Corner: Test key failure connectivity error payload check
    create_res = client.post("/api/v1/api-keys", json={
        "provider": "openai", "label": "UI Fail Key", "api_key": "sk-fail-openai-key-value"
    })
    key_id = create_res.json()["id"]
    
    response = client.post(f"/api/v1/api-keys/{key_id}/test")
    assert response.status_code == 400
    assert "Connectivity test failed" in response.json()["detail"]

def test_settings_theme_dark_mode_active(client):
    # Tier 2 - Boundary/Corner: Theme dark mode configuration parameters active check
    response = client.get("/api/v1/ui/settings/theme")
    assert response.status_code == 200
    data = response.json()
    assert data["theme"] == "dark"
    assert "blur" in data["background_blur"]
    assert data["border_opacity"] > 0.0
