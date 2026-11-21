"""Structured managed-model reason propagation tests (mocked/in-memory only)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai import llm as llm_module
from app.ai.llm import ManagedModelError
from app.pipeline import orchestrator as pipeline_module
from app.pipeline.orchestrator import review_pipeline
from app.queue import worker as worker_module
from app.services import kllm_service
from app.services.kllm_service import KllmUnavailableError
from app.services.review_execution_service import create_execution, get_latest_execution
from app.services.review_selection import selection_api_fields_from_values


class _DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


async def test_managed_ready_failure_keeps_structured_reason(monkeypatch):
    async def forbidden_ready(*_args, **_kwargs):
        raise KllmUnavailableError(
            "Timed out after 60s waiting for model 'qwen3.8-27b'.",
            reason_code="load_timeout",
        )

    import importlib

    autoload_module = importlib.import_module("app.services.kllm_autoload")
    monkeypatch.setattr(llm_module, "AsyncSessionLocal", lambda: _DummySession())
    monkeypatch.setattr(
        autoload_module, "ensure_model_ready_with_autoload", forbidden_ready
    )

    with pytest.raises(ManagedModelError) as exc:
        await llm_module.llm_service._ensure_managed_ready("qwen3.8-27b")
    assert exc.value.reason_code == "load_timeout"


async def test_pipeline_failure_persists_authoritative_reason(test_db, monkeypatch):
    from app.models.review import Review

    review = Review(pr_id=uuid.uuid4(), status="running")
    test_db.add(review)
    await test_db.commit()
    await test_db.refresh(review)
    await create_execution(test_db, review.id, trigger="webhook")
    await test_db.commit()

    class SessionWrapper:
        async def __aenter__(self):
            return test_db

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", lambda: SessionWrapper())
    await review_pipeline._save_failed(
        review.id, "Model load timed out", reason_code="load_timeout"
    )

    execution = await get_latest_execution(test_db, review.id)
    readiness = (execution.configuration_snapshot or {}).get("kllm_readiness")
    assert readiness["reason_code"] == "load_timeout"
    assert readiness["state"] == "unavailable"


async def test_worker_refresh_preserves_authoritative_reason(
    test_db, monkeypatch
):
    from app.models.review import Review

    monkeypatch.setattr(
        worker_module.settings, "KLLM_ENABLED", True, raising=False
    )

    review = Review(pr_id=uuid.uuid4(), status="failed")
    test_db.add(review)
    await test_db.commit()
    await test_db.refresh(review)
    execution = await create_execution(
        test_db,
        review.id,
        trigger="webhook",
        provider="kllm",
        model="qwen3.8-27b",
        configuration_snapshot={
            "kllm_readiness": {
                "model": "qwen3.8-27b",
                "state": "unavailable",
                "reason_code": "load_timeout",
                "checked_at": datetime.now(UTC).isoformat(),
            }
        },
    )
    execution.status = "failed"
    test_db.add(execution)
    await test_db.commit()

    class SessionWrapper:
        async def __aenter__(self):
            return test_db

        async def __aexit__(self, *_exc):
            return False

    async def fake_snapshot(db, *, force=False):
        return kllm_service.KllmSnapshot(
            enabled=True,
            configured=True,
            reachable=True,
            stale=False,
            generated_at=datetime.now(UTC),
            age_seconds=0,
            error=None,
            relay_health={"ok": True, "inflight": 0},
            models=[
                kllm_service.KllmModel(
                    key="qwen3.8-27b",
                    status="unloaded",
                    loaded=False,
                    ready=False,
                    context_window=None,
                    vision=False,
                    readiness="unloaded",
                    reason_code="model_unloaded",
                )
            ],
            backends=[],
            pending=[],
            summary={},
            clients=[],
            traffic={},
            supervisor=False,
            autoscale=False,
        )

    import importlib

    provider_module = importlib.import_module("app.services.provider_registry")
    monkeypatch.setattr(worker_module, "AsyncSessionLocal", lambda: SessionWrapper())
    monkeypatch.setattr(kllm_service, "get_snapshot", fake_snapshot)
    monkeypatch.setattr(
        provider_module.provider_registry_service,
        "get_by_identifier",
        AsyncMock(return_value=SimpleNamespace(is_managed=True)),
    )

    await worker_module._record_kllm_readiness(review.id, "kllm", "qwen3.8-27b")

    refreshed = await get_latest_execution(test_db, review.id)
    readiness = (refreshed.configuration_snapshot or {})["kllm_readiness"]
    assert readiness["reason_code"] == "load_timeout"


def test_api_projection_exposes_timeout_reason():
    fields = selection_api_fields_from_values(
        {
            "kllm_readiness": {
                "model": "qwen3.8-27b",
                "state": "unavailable",
                "reason_code": "load_timeout",
                "checked_at": "2026-11-21T00:00:00+00:00",
            }
        },
        "kllm",
        "qwen3.8-27b",
        "failed",
        datetime.now(UTC),
        {},
    )
    assert fields["kllm_readiness"]["reason_code"] == "load_timeout"
