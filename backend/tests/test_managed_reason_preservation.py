"""Managed lifecycle reason preservation across fallback routes."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.ai.llm import ManagedModelError
from app.orchestrator.models import FallbackRoute
from app.orchestrator.orchestrator import llm_orchestrator
from app.pipeline import orchestrator as pipeline_module
from app.pipeline.orchestrator import review_pipeline

MODEL = "qwen3.8-27b"


class _Prompt:
    total_tokens = 10

    def get_user_messages(self):
        return [{"role": "user", "content": "hi"}]


class _Emitter:
    async def emit(self, *_args, **_kwargs):
        return None

    async def emit_log(self, *_args, **_kwargs):
        return None

    async def emit_error(self, *_args, **_kwargs):
        return None


class _DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, *_args, **_kwargs):
        class _Result:
            def scalars(self):
                return self

            def first(self):
                return None

        return _Result()

    async def commit(self):
        return None


async def test_managed_timeout_survives_later_generic_fallback_failure():
    calls = []

    async def get_completion(user_id, provider, messages, model, api_key_id=None, cancel_check=None):
        calls.append((provider, model))
        if provider == "kllm":
            raise ManagedModelError("Timed out waiting for model", "load_timeout")
        raise RuntimeError("fallback provider unavailable")

    with patch(
        "app.orchestrator.orchestrator.llm_service.get_completion",
        new=get_completion,
    ):
        with pytest.raises(ManagedModelError) as exc:
            await llm_orchestrator.complete(
                prompt=_Prompt(),
                user_id="00000000-0000-0000-0000-000000000000",
                config_source="repo_config",
                preferred_provider="kllm",
                preferred_model=MODEL,
                api_key_id=None,
                fallback_routes=[
                    FallbackRoute(provider="gemini", model="gemini-2.5-flash", api_key_id=None)
                ],
            )
    assert exc.value.reason_code == "load_timeout"
    assert calls == [("kllm", MODEL), ("gemini", "gemini-2.5-flash")]


async def test_managed_manual_unload_survives_later_generic_fallback_failure():
    async def get_completion(user_id, provider, messages, model, api_key_id=None, cancel_check=None):
        if provider == "kllm":
            raise ManagedModelError("Auto-load blocked by admin", "manual_unload")
        raise RuntimeError("fallback failed generically")

    with patch(
        "app.orchestrator.orchestrator.llm_service.get_completion",
        new=get_completion,
    ):
        with pytest.raises(ManagedModelError) as exc:
            await llm_orchestrator.complete(
                prompt=_Prompt(),
                user_id="00000000-0000-0000-0000-000000000000",
                config_source="repo_config",
                preferred_provider="kllm",
                preferred_model=MODEL,
                fallback_routes=[
                    FallbackRoute(provider="openai", model="gpt-4o", api_key_id=None)
                ],
            )
    assert exc.value.reason_code == "manual_unload"


async def test_managed_errors_have_deterministic_first_error_precedence():
    async def get_completion(user_id, provider, messages, model, api_key_id=None, cancel_check=None):
        if provider == "kllm":
            raise ManagedModelError("first managed reason", "load_timeout")
        raise ManagedModelError("second managed reason", "manual_unload")

    with patch(
        "app.orchestrator.orchestrator.llm_service.get_completion",
        new=get_completion,
    ):
        with pytest.raises(ManagedModelError) as exc:
            await llm_orchestrator.complete(
                prompt=_Prompt(),
                user_id="00000000-0000-0000-0000-000000000000",
                config_source="repo_config",
                preferred_provider="kllm",
                preferred_model=MODEL,
                fallback_routes=[
                    FallbackRoute(provider="gemini", model="gemini-2.5-flash", api_key_id=None)
                ],
            )
    assert exc.value.reason_code == "load_timeout"


async def test_generic_primary_failure_with_successful_fallback():
    async def get_completion(user_id, provider, messages, model, api_key_id=None, cancel_check=None):
        if provider == "kllm":
            raise RuntimeError("generic kLLM failure")
        return "ok", 5, 5

    with patch(
        "app.orchestrator.orchestrator.llm_service.get_completion",
        new=get_completion,
    ):
        response = await llm_orchestrator.complete(
            prompt=_Prompt(),
            user_id="00000000-0000-0000-0000-000000000000",
            config_source="repo_config",
            preferred_provider="kllm",
            preferred_model=MODEL,
            fallback_routes=[
                FallbackRoute(provider="gemini", model="gemini-2.5-flash", api_key_id=None)
            ],
        )
    assert response.is_fallback is True
    assert response.provider == "gemini"


async def test_managed_failure_with_successful_fallback_does_not_report_timeout():
    async def get_completion(user_id, provider, messages, model, api_key_id=None, cancel_check=None):
        if provider == "kllm":
            raise ManagedModelError("Timed out waiting for model", "load_timeout")
        return "ok", 5, 5

    with patch(
        "app.orchestrator.orchestrator.llm_service.get_completion",
        new=get_completion,
    ):
        response = await llm_orchestrator.complete(
            prompt=_Prompt(),
            user_id="00000000-0000-0000-0000-000000000000",
            config_source="repo_config",
            preferred_provider="kllm",
            preferred_model=MODEL,
            fallback_routes=[
                FallbackRoute(provider="gemini", model="gemini-2.5-flash", api_key_id=None)
            ],
        )
    assert response.content == "ok"
    assert response.is_fallback is True


async def test_all_generic_failures_keep_existing_generic_behavior():
    async def get_completion(user_id, provider, messages, model, api_key_id=None, cancel_check=None):
        raise RuntimeError("all routes failed")

    with patch(
        "app.orchestrator.orchestrator.llm_service.get_completion",
        new=get_completion,
    ):
        with pytest.raises(RuntimeError) as exc:
            await llm_orchestrator.complete(
                prompt=_Prompt(),
                user_id="00000000-0000-0000-0000-000000000000",
                config_source="repo_config",
                preferred_provider="kllm",
                preferred_model=MODEL,
            )
    assert not isinstance(exc.value, ManagedModelError)
    assert "all routes failed" in str(exc.value)


async def test_cancellation_during_fallback_keeps_cancellation_semantics():
    checks = 0

    async def cancel_check():
        nonlocal checks
        checks += 1
        return checks > 1

    async def get_completion(user_id, provider, messages, model, api_key_id=None, cancel_check=None):
        if provider == "kllm":
            raise RuntimeError("primary failed")
        return "ok", 5, 5

    with patch(
        "app.orchestrator.orchestrator.llm_service.get_completion",
        new=get_completion,
    ):
        with pytest.raises(asyncio.CancelledError):
            await llm_orchestrator.complete(
                prompt=_Prompt(),
                user_id="00000000-0000-0000-0000-000000000000",
                config_source="repo_config",
                preferred_provider="kllm",
                preferred_model=MODEL,
                fallback_routes=[
                    FallbackRoute(provider="gemini", model="gemini-2.5-flash", api_key_id=None)
                ],
                cancel_check=cancel_check,
            )


async def test_pipeline_passes_authoritative_reason_to_failure_persistence(monkeypatch):
    save_failed = AsyncMock()
    monkeypatch.setattr(review_pipeline, "_stage_clone", AsyncMock(return_value=None))
    monkeypatch.setattr(review_pipeline, "_stage_intelligence", AsyncMock(return_value={}))
    monkeypatch.setattr(review_pipeline, "_stage_indexing", AsyncMock(return_value=None))
    monkeypatch.setattr(
        review_pipeline, "_stage_knowledge", AsyncMock(return_value=("", [], None))
    )
    monkeypatch.setattr(review_pipeline, "_stage_retrieval", AsyncMock(return_value=None))
    monkeypatch.setattr(review_pipeline, "_stage_prompt", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        review_pipeline,
        "_stage_llm",
        AsyncMock(side_effect=ManagedModelError("Timed out", "load_timeout")),
    )
    monkeypatch.setattr(review_pipeline, "_save_failed", save_failed)
    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", lambda: _DummySession())
    monkeypatch.setattr(pipeline_module, "SSEEmitter", lambda *_args: _Emitter())
    monkeypatch.setattr("app.services.timeline_recorder.record_stage", AsyncMock())

    await review_pipeline.execute(
        review_id=uuid.uuid4(),
        installation_id=1,
        owner="owner",
        repo_name="repo",
        pr_number=1,
        pr_title="title",
        pr_description="",
        head_sha="abc",
        diff_content="",
        user_id="00000000-0000-0000-0000-000000000000",
        provider="kllm",
        model=MODEL,
    )

    save_failed.assert_awaited_once()
    assert save_failed.await_args.kwargs["reason_code"] == "load_timeout"
