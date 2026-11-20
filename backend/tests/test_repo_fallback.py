"""Tests for repository-level fallback preference and primary-first routing.

All external providers and kLLM are mocked. No real inference or model ops.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.models.github import Repository
from app.services.model_router import ModelRoute, model_router
from app.services.provider_registry import ProviderUnavailableError
from app.services.review_selection import resolve_selection, selection_api_fields_from_values


async def _seed_repo(db, user, *, settings=None):
    from app.models.github import Installation

    installation = Installation(
        installation_id=99002,
        account_id=4243,
        account_login="acct2",
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
        name="demo2",
        full_name="acct2/demo2",
        installation_id=installation.id,
        reviews_enabled=True,
        settings=settings or {},
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return repo


async def test_resolve_selection_fallback_disabled_unresolved(
    test_db, mock_user, monkeypatch
):
    repo = await _seed_repo(
        test_db,
        mock_user,
        settings={
            "assigned_provider": "kllm",
            "assigned_model": "qwen3.8-27b",
            "fallback_enabled": False,
        },
    )

    async def _raise(*a, **kw):
        raise ProviderUnavailableError("kllm", "model unavailable")

    monkeypatch.setattr(
        "app.github.shared.resolve_provider_config", _raise
    )

    selection = await resolve_selection(test_db, str(mock_user.id), repo)
    assert selection.is_resolved is False
    assert selection.provider is None
    assert selection.fallback_used is False
    assert selection.error is not None


async def test_resolve_selection_fallback_enabled_uses_router(
    test_db, mock_user, monkeypatch
):
    repo = await _seed_repo(
        test_db,
        mock_user,
        settings={
            "assigned_provider": "kllm",
            "assigned_model": "qwen3.8-27b",
            "fallback_enabled": True,
        },
    )

    async def _raise(*a, **kw):
        raise ProviderUnavailableError("kllm", "model unavailable")

    monkeypatch.setattr("app.github.shared.resolve_provider_config", _raise)

    fallback_route = ModelRoute(
        provider="gemini",
        model="gemini-2.5-flash",
        litellm_model="gemini/gemini-2.5-flash",
        api_key_id=None,
        estimated_cost_per_1k=0.0,
    )
    monkeypatch.setattr(
        model_router,
        "route_excluding",
        AsyncMock(return_value=fallback_route),
    )

    selection = await resolve_selection(test_db, str(mock_user.id), repo)
    assert selection.is_resolved is True
    assert selection.provider == "gemini"
    assert selection.model == "gemini-2.5-flash"
    assert selection.fallback_used is True
    assert selection.fallback_provider == "kllm"
    assert selection.fallback_model == "qwen3.8-27b"
    assert selection.fallback_reason == "primary_unavailable"
    # Source records that a routing fallback was used.
    assert selection.source == "user_routing"


async def test_route_excluding_skips_primary():
    primary = ModelRoute(
        provider="kllm",
        model="qwen3.8-27b",
        litellm_model="openai/qwen3.8-27b",
        api_key_id=None,
        estimated_cost_per_1k=0.0,
    )
    alternative = ModelRoute(
        provider="gemini",
        model="gemini-2.5-flash",
        litellm_model="gemini/gemini-2.5-flash",
        api_key_id="key-1",
        estimated_cost_per_1k=0.0,
    )

    async def _route(*a, **kw):
        return [primary, alternative]

    with patch.object(model_router, "route", new=_route):
        result = await model_router.route_excluding(
            None,  # db not used by patched route
            uuid.uuid4(),
            "code_review",
            exclude={("kllm", "qwen3.8-27b")},
        )
    assert result is not None
    assert result.provider == "gemini"
    assert result.model == "gemini-2.5-flash"


async def test_route_excluding_returns_none_when_no_alternative():
    primary = ModelRoute(
        provider="kllm",
        model="qwen3.8-27b",
        litellm_model="openai/qwen3.8-27b",
        api_key_id=None,
        estimated_cost_per_1k=0.0,
    )

    async def _route(*a, **kw):
        return [primary]

    with patch.object(model_router, "route", new=_route):
        result = await model_router.route_excluding(
            None,
            uuid.uuid4(),
            "code_review",
            exclude={("kllm", "qwen3.8-27b")},
        )
    assert result is None


async def test_repo_config_persists_fallback_enabled(
    test_db, anon_client, user_auth_token, mock_user
):
    import uuid as _uuid

    from tests.test_provider_controls import _seed_repo

    repo = await _seed_repo(test_db, mock_user)

    from tests.test_provider_controls import _as_user as as_user

    client = as_user(anon_client, user_auth_token)
    response = client.patch(
        f"/api/v1/repositories/{repo.id}/config",
        json={"fallback_enabled": True},
    )
    assert response.status_code == 200, response.text
    await test_db.refresh(repo)
    assert (repo.settings or {}).get("fallback_enabled") is True
    assert response.json().get("fallback_enabled") is True


async def test_selection_api_fields_fallback_used():
    snapshot = {
        "selection": {
            "repository_mapping_status": "mapped",
            "repository_provider": "kllm",
            "repository_model": "qwen3.8-27b",
            "selection_source": "repository_mapping",
            "selected_provider": "gemini",
            "selected_provider_slug": "gemini",
            "selected_provider_name": "Gemini",
            "selected_model": "gemini-2.5-flash",
            "selected_api_key_id": None,
            "error": None,
            "resolved_at": "2026-01-01T00:00:00+00:00",
            "fallback_used": True,
            "fallback_reason": "primary_unavailable",
        }
    }
    fields = selection_api_fields_from_values(
        snapshot,
        "gemini",
        "gemini-2.5-flash",
        "completed",
        None,
        {"fallback_used": True},
    )
    assert fields["fallback_used"] is True
    assert fields["fallback_reason"] == "primary_unavailable"

    # Inference-time fallback recorded only in stats.
    fields2 = selection_api_fields_from_values(
        None, "gemini", "gemini-2.5-flash", "completed", None, {"fallback_used": True}
    )
    assert fields2["fallback_used"] is True


async def test_orchestrator_cancellation_before_fallback():
    from app.orchestrator.models import FallbackRoute
    from app.orchestrator.orchestrator import llm_orchestrator

    class _Prompt:
        total_tokens = 10

        def get_user_messages(self):
            return [{"role": "user", "content": "hi"}]

    prompt = _Prompt()
    calls = []

    async def _get_completion(user_id, provider, messages, model, api_key_id=None):
        calls.append((provider, model))
        if provider == "kllm":
            raise RuntimeError("model unavailable")
        return "ok", 5, 5

    cancel_calls = {"n": 0}

    async def _cancel_check():
        cancel_calls["n"] += 1
        return cancel_calls["n"] >= 2

    with patch("app.orchestrator.orchestrator.llm_service.get_completion", new=_get_completion):
        try:
            await llm_orchestrator.complete(
                prompt=prompt,  # type: ignore[arg-type]
                user_id="00000000-0000-0000-0000-000000000000",
                config_source="repo_config",
                preferred_provider="kllm",
                preferred_model="qwen3.8-27b",
                api_key_id=None,
                fallback_routes=[
                    FallbackRoute(provider="gemini", model="gemini-2.5-flash", api_key_id=None)
                ],
                cancel_check=_cancel_check,
            )
            raised = False
        except asyncio.CancelledError:
            raised = True
    assert raised is True
    assert calls == [("kllm", "qwen3.8-27b")]


async def test_pipeline_cancellation_skips_publish():
    from unittest.mock import AsyncMock

    import uuid

    from app.pipeline.orchestrator import review_pipeline

    publish_calls = []

    async def fake_publish(*a, **kw):
        publish_calls.append(True)
        return "body"

    review_pipeline._stage_clone = AsyncMock(return_value=None)
    review_pipeline._stage_intelligence = AsyncMock(return_value={})
    review_pipeline._stage_indexing = AsyncMock(return_value=None)
    review_pipeline._stage_knowledge = AsyncMock(return_value=("", [], None))
    review_pipeline._stage_retrieval = AsyncMock(return_value=None)
    review_pipeline._stage_prompt = AsyncMock(return_value=object())
    review_pipeline._stage_verification = AsyncMock(
        return_value=type("V", (), {"verified_count": 0, "rejected_count": 0, "to_dict": lambda self: {}})()
    )
    review_pipeline._stage_publish = AsyncMock(side_effect=fake_publish)

    async def _cancelled_llm(*a, **kw):
        raise asyncio.CancelledError()

    review_pipeline._stage_llm = AsyncMock(side_effect=_cancelled_llm)

    try:
        await review_pipeline.execute(
            review_id=uuid.uuid4(),
            installation_id=1,
            owner="o",
            repo_name="r",
            pr_number=1,
            pr_title="t",
            pr_description="",
            head_sha="abc",
            diff_content="",
            user_id="00000000-0000-0000-0000-000000000000",
            provider="kllm",
            model="qwen3.8-27b",
            cancel_check=lambda: False,
        )
        raised = False
    except asyncio.CancelledError:
        raised = True
    assert raised is True
    assert publish_calls == []


async def test_orchestrator_fallback_tries_alternative():
    from app.orchestrator.models import FallbackRoute
    from app.orchestrator.orchestrator import llm_orchestrator
    from app.prompt_engine.models import CompiledPrompt

    # Minimal prompt stub.
    class _Prompt:
        total_tokens = 10

        def get_user_messages(self):
            return [{"role": "user", "content": "hi"}]

    prompt = _Prompt()

    calls = []

    async def _get_completion(user_id, provider, messages, model, api_key_id=None):
        calls.append((provider, model))
        if provider == "kllm":
            raise RuntimeError("model unavailable")
        return "ok", 5, 5

    with patch("app.orchestrator.orchestrator.llm_service.get_completion", new=_get_completion):
        response = await llm_orchestrator.complete(
            prompt=prompt,  # type: ignore[arg-type]
            user_id="00000000-0000-0000-0000-000000000000",
            config_source="repo_config",
            preferred_provider="kllm",
            preferred_model="qwen3.8-27b",
            api_key_id=None,
            fallback_routes=[
                FallbackRoute(provider="gemini", model="gemini-2.5-flash", api_key_id=None)
            ],
        )
    assert response.provider == "gemini"
    assert response.model == "gemini-2.5-flash"
    assert response.is_fallback is True
    assert calls == [("kllm", "qwen3.8-27b"), ("gemini", "gemini-2.5-flash")]