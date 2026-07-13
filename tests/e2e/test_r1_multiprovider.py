# MANDATORY INTEGRITY WARNING:
# DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results,
# create dummy/facade implementations, or circumvent the intended task. A Forensic
# Auditor will independently verify your work. Integrity violations WILL be detected
# and your work WILL be rejected.

import pytest
import uuid
import asyncio
from sqlalchemy import select
from conftest import LlmUsage, MOCK_USER_ID, TestSessionLocal
from app.prompt_engine.models import CompiledPrompt
from app.orchestrator.orchestrator import llm_orchestrator

def test_openai_completion_success(mock_llm_completion):
    # Tier 1 - Feature Coverage: OpenAI completion
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=10)
    response = asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="openai"))
    
    assert response.content == "OpenAI mock response content."
    assert response.provider == "openai"
    assert response.model == "gpt-4o"
    assert not response.is_fallback

def test_anthropic_completion_success(mock_llm_completion):
    # Tier 1 - Feature Coverage: Anthropic completion
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=15)
    response = asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="anthropic"))
    
    assert response.content == "Anthropic mock response content."
    assert response.provider == "anthropic"
    assert "claude" in response.model
    assert not response.is_fallback

def test_gemini_completion_success(mock_llm_completion):
    # Tier 1 - Feature Coverage: Gemini completion
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=20)
    response = asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="gemini"))
    
    assert response.content == "Gemini mock response content."
    assert response.provider == "gemini"
    assert "gemini" in response.model
    assert not response.is_fallback

def test_groq_completion_success(mock_llm_completion):
    # Tier 1 - Feature Coverage: Groq completion
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=25)
    response = asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="groq"))
    
    assert response.content == "Groq mock response content."
    assert response.provider == "groq"
    assert "llama" in response.model
    assert not response.is_fallback

def test_deepseek_completion_success(mock_llm_completion):
    # Tier 1 - Feature Coverage: DeepSeek completion
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=30)
    response = asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="deepseek"))
    
    assert response.content == "DeepSeek mock response content."
    assert response.provider == "deepseek"
    assert "deepseek" in response.model
    assert not response.is_fallback

def test_usage_stats_persistence_on_success(mock_llm_completion):
    # Tier 1 - Feature Coverage: Persisting usage stats into database
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=50)
    response = asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="openai"))
    
    # Query SQLite database to verify persistence
    async def query_db():
        async with TestSessionLocal() as session:
            result = await session.execute(select(LlmUsage).where(LlmUsage.user_id == MOCK_USER_ID))
            return result.scalars().all()
            
    usage_records = asyncio.run(query_db())
    
    assert len(usage_records) == 1
    record = usage_records[0]
    assert record.provider == "openai"
    assert record.model == "gpt-4o"
    assert record.input_tokens == 50
    assert record.estimated_cost_usd > 0.0

def test_retry_logic_on_rate_limit(monkeypatch, mock_llm_completion):
    # Tier 2 - Boundary/Corner: Retry logic on transient failures
    # Mocking sleep to prevent tests from being slow
    sleep_calls = []
    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=10)
    
    # We pass 'fail_once' in env or setup so the first attempt raises a rate limit exception,
    # and second attempt works. In conftest.py, we mocked fail_once to cause RuntimeError on first call.
    from app.services.api_key_service import api_key_service
    async def mock_key(*args):
        return "fail_once_key"
    monkeypatch.setattr(api_key_service, "get_decrypted_key", mock_key)
    
    response = asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="openai"))
    
    assert response.content == "OpenAI mock response content."
    assert response.provider == "openai"
    assert len(sleep_calls) == 1

def test_fallback_to_next_priority_provider(monkeypatch, mock_llm_completion):
    # Tier 2 - Boundary/Corner: Provider fallback when preferred fails persistently
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=10)
    
    # Force preferred provider to fail persistently
    from app.services.api_key_service import api_key_service
    async def mock_key(db, user_id, provider):
        if provider == "gemini":
            return "fail_always_key"
        return f"sk-proj-{provider}-mock-key"
    monkeypatch.setattr(api_key_service, "get_decrypted_key", mock_key)
    
    # Let's verify gemini is preferred but fails, falling back to openai
    response = asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="gemini"))
    
    # It fallback because gemini is key "fail_always" which throws error.
    # The orchestrator will try gemini, fail 3 times, then try openai which will succeed!
    assert response.provider == "openai"
    assert response.is_fallback

def test_all_providers_fail_raises_runtime_error(monkeypatch, mock_llm_completion):
    # Tier 2 - Boundary/Corner: Error handling when all providers fail
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=10)
    
    # Force llm_service to throw exception for all providers
    async def fake_get_completion(*args, **kwargs):
        raise RuntimeError("Persistent network error")
    monkeypatch.setattr("app.orchestrator.orchestrator.llm_service.get_completion", fake_get_completion)
    
    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID)))
    
    assert "All LLM providers failed" in str(exc_info.value)

def test_cost_estimation_calculation(mock_llm_completion):
    # Tier 2 - Boundary/Corner: Cost estimation mathematics
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=1000)
    response = asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="openai"))
    assert abs(response.estimated_cost_usd - 0.00257) < 0.0001

def test_orchestrator_updates_success_rate_on_failure(monkeypatch, mock_llm_completion):
    # Tier 2 - Boundary/Corner: Success rate tracking on failures
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=10)
    
    # Let's reset groq's success rate and check it degrades
    provider_config = llm_orchestrator.providers["groq"]
    provider_config.success_rate = 1.0
    
    async def fake_get_completion(*args, **kwargs):
        raise RuntimeError("Failure")
    monkeypatch.setattr("app.orchestrator.orchestrator.llm_service.get_completion", fake_get_completion)
    
    try:
        asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="groq"))
    except Exception:
        pass
        
    assert provider_config.success_rate < 1.0

def test_orchestrator_updates_success_rate_on_success(mock_llm_completion):
    # Tier 2 - Boundary/Corner: Success rate capped at 1.0
    prompt = CompiledPrompt(system_prompt="System", user_prompt="Hello", total_tokens=10)
    
    provider_config = llm_orchestrator.providers["openai"]
    provider_config.success_rate = 0.9
    
    asyncio.run(llm_orchestrator.complete(prompt, str(MOCK_USER_ID), preferred_provider="openai"))
    
    assert provider_config.success_rate == pytest.approx(0.95)
