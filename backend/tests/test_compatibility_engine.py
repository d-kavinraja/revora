import pytest
from app.ai.model_registry import canonical_registry, CanonicalModel
from app.services.model_discovery import ModelDiscoveryEngine
from app.ai.llm import LLMService

@pytest.fixture(autouse=True)
def setup_teardown_registry():
    canonical_registry.clear()
    yield
    canonical_registry.clear()

def test_canonical_model_registration_and_resolution():
    model = CanonicalModel(
        provider="gemini",
        provider_model_name="gemini-2.5-flash-lite",
        canonical_model_name="gemini-2.5-flash-lite",
        litellm_model_name="gemini/gemini-2.5-flash-lite",
        model_name="gemini-2.5-flash-lite"
    )
    
    canonical_registry.register(model)
    
    # Resolve by canonical name
    resolved = canonical_registry.resolve("gemini", "gemini-2.5-flash-lite")
    assert resolved is not None
    assert resolved.canonical_model_name == "gemini-2.5-flash-lite"
    
    # Resolve by litellm name
    resolved = canonical_registry.resolve("gemini", "gemini/gemini-2.5-flash-lite")
    assert resolved is not None
    assert resolved.canonical_model_name == "gemini-2.5-flash-lite"
    
    # Resolve when prefixed unexpectedly
    resolved = canonical_registry.resolve("gemini", "gemini/gemini-2.5-flash-lite")
    assert resolved is not None

def test_model_discovery_normalization():
    model = ModelDiscoveryEngine._enrich_model("gemini-2.5-flash-lite", "gemini")
    assert model.canonical_model_name == "gemini-2.5-flash-lite"
    assert model.litellm_model_name == "gemini/gemini-2.5-flash-lite"
    
    model2 = ModelDiscoveryEngine._enrich_model("models/gemini-1.5-pro", "gemini")
    assert model2.canonical_model_name == "gemini-1.5-pro"
    assert model2.litellm_model_name == "gemini/gemini-1.5-pro"
    
    model3 = ModelDiscoveryEngine._enrich_model("claude-3-5-sonnet-20240620", "anthropic")
    assert model3.canonical_model_name == "claude-3-5-sonnet-20240620"
    assert model3.litellm_model_name == "anthropic/claude-3-5-sonnet-20240620"

def test_llm_service_resolve_model():
    # Setup registry
    model = CanonicalModel(
        provider="gemini",
        provider_model_name="gemini-2.5-flash-lite",
        canonical_model_name="gemini-2.5-flash-lite",
        litellm_model_name="gemini/gemini-2.5-flash-lite",
        model_name="gemini-2.5-flash-lite"
    )
    canonical_registry.register(model)
    
    llm_service = LLMService()
    
    litellm_name, canonical_model = llm_service._resolve_model("gemini", "gemini-2.5-flash-lite")
    assert litellm_name == "gemini/gemini-2.5-flash-lite"
    assert canonical_model is not None
    
    litellm_name, canonical_model = llm_service._resolve_model("gemini", "gemini/gemini-2.5-flash-lite")
    assert litellm_name == "gemini/gemini-2.5-flash-lite"
    assert canonical_model is not None
    
    # Unregistered model fallback
    litellm_name, canonical_model = llm_service._resolve_model("gemini", "gemini-unknown-model")
    assert litellm_name == "gemini/gemini-unknown-model"
    assert canonical_model is None
