"""Deterministic model-identity and request-isolation tests.

The provider clients are replaced with in-process recorders. No test contacts
a gateway, loads a model, or performs inference.
"""

from __future__ import annotations

import pytest

from app.ai.hosted_ollama_client import _build_payload as build_hosted_payload
from app.ai.kllm_client import _build_payload as build_kllm_payload
from app.ai.llm import llm_service
from app.core import config as config_module
from app.models.provider import ProviderRegistry
from app.services import hosted_ollama_service as hosted
from app.services import kllm_service
from app.services.chat_service import reset_chat_runtime_state
from app.services.hosted_ollama_service import HostedModel, hosted_key
from app.services.kllm_service import KllmModel

KLLM_MODEL = "qwen3.8-27b"
HOSTED_MODEL = "phi4-mini:3.8b"
HOSTED_KEY = hosted_key(HOSTED_MODEL)


@pytest.fixture(autouse=True)
def _reset():
    reset_chat_runtime_state()
    hosted.reset_runtime_state()
    yield
    reset_chat_runtime_state()
    hosted.reset_runtime_state()


@pytest.fixture(autouse=True)
def _patch_chat_db(test_db, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        yield test_db

    monkeypatch.setattr("app.api.v1.endpoints.chat.AsyncSessionLocal", _cm)


@pytest.fixture
def gateway_enabled(monkeypatch):
    monkeypatch.setattr(config_module.settings, "KLLM_ENABLED", True, raising=False)
    return True


async def _seed_managed_provider(db) -> ProviderRegistry:
    provider = ProviderRegistry(
        name="kllm",
        display_name="kLLM",
        slug="kllm",
        litellm_provider="openai",
        default_model=KLLM_MODEL,
        api_key_min_length=1,
        is_enabled=True,
        status="available",
        is_managed=True,
        allow_key_addition=False,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


def _kllm_model() -> KllmModel:
    return KllmModel(
        key=KLLM_MODEL,
        status="loaded",
        loaded=True,
        ready=True,
        readiness="ready",
        reason_code="ready",
        context_window=131_072,
        vision=False,
        tags=[],
        backend_count=1,
    )


CONVERSATION = [
    {"role": "user", "content": "What is machine learning?"},
    {"role": "assistant", "content": "It is a field of statistics."},
    {"role": "user", "content": "What are its three major types?"},
    {"role": "assistant", "content": "Supervised, unsupervised, reinforcement."},
    {"role": "user", "content": "Explain the second type in more detail."},
]


# --- payload builders -----------------------------------------------------


def test_hosted_payload_preserves_the_bare_model_name():
    payload = build_hosted_payload(
        HOSTED_MODEL, CONVERSATION, stream=False, max_tokens=256, temperature=None
    )
    assert payload["model"] == HOSTED_MODEL
    assert payload["messages"] == CONVERSATION


def test_kllm_payload_preserves_the_canonical_model_name():
    payload = build_kllm_payload(
        KLLM_MODEL,
        CONVERSATION,
        stream=False,
        max_tokens=256,
        temperature=None,
        reasoning_effort=None,
    )
    assert payload["model"] == KLLM_MODEL
    assert payload["messages"] == CONVERSATION


def test_payloads_never_add_a_system_turn_or_identity_instruction():
    for payload in (
        build_hosted_payload(HOSTED_MODEL, CONVERSATION, stream=True, max_tokens=256, temperature=None),
        build_kllm_payload(
            KLLM_MODEL,
            CONVERSATION,
            stream=True,
            max_tokens=256,
            temperature=None,
            reasoning_effort=None,
        ),
    ):
        roles = [message["role"] for message in payload["messages"]]
        assert roles == ["user", "assistant", "user", "assistant", "user"]
        assert all(message["content"] == CONVERSATION[i]["content"] for i, message in enumerate(payload["messages"]))
        joined = " ".join(message["content"] for message in payload["messages"]).lower()
        assert "you are" not in joined
        assert "phi" not in joined
        assert "microsoft" not in joined


def test_payload_builders_copy_the_caller_message_list():
    messages = [dict(message) for message in CONVERSATION]
    payload = build_hosted_payload(
        HOSTED_MODEL, messages, stream=False, max_tokens=256, temperature=None
    )
    assert payload["messages"] is not messages
    messages.append({"role": "user", "content": "later mutation"})
    assert len(payload["messages"]) == len(CONVERSATION)


def test_two_payloads_do_not_share_mutable_message_lists():
    first = build_hosted_payload(
        "llama3.2:3b", CONVERSATION, stream=False, max_tokens=256, temperature=None
    )
    second = build_kllm_payload(
        KLLM_MODEL,
        CONVERSATION,
        stream=False,
        max_tokens=256,
        temperature=None,
        reasoning_effort=None,
    )
    assert first["messages"] is not second["messages"]
    first["messages"].append({"role": "user", "content": "contaminated"})
    assert len(second["messages"]) == len(CONVERSATION)


# --- routing --------------------------------------------------------------


async def test_hosted_request_keeps_the_selected_model_key(client, test_db, monkeypatch):
    captured = {}

    async def fake_ensure(_db, _key):
        return HostedModel(key=HOSTED_KEY, model=HOSTED_MODEL, context_window=8192, ready=True)

    async def fake_complete(model, messages, **_kwargs):
        captured["model"] = model
        captured["messages"] = messages
        return "ok", 1, 1

    monkeypatch.setattr(hosted, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_hosted", fake_complete)

    response = client.post(
        "/api/v1/chat/completions",
        json={"model": HOSTED_KEY, "messages": CONVERSATION, "stream": False},
    )
    assert response.status_code == 200, response.text
    # The provider receives the bare Ollama name; the client keeps the key.
    assert captured["model"] == HOSTED_MODEL
    assert response.json()["model"] == HOSTED_KEY
    assert captured["messages"] == CONVERSATION


async def test_kllm_request_keeps_the_selected_model_key(
    client, test_db, gateway_enabled, monkeypatch
):
    await _seed_managed_provider(test_db)
    captured = {}

    async def fake_ensure(_db, _model):
        return _kllm_model()

    async def fake_complete(model, messages, **_kwargs):
        captured["model"] = model
        captured["messages"] = messages
        return "ok", 1, 1

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)

    response = client.post(
        "/api/v1/chat/completions",
        json={"model": KLLM_MODEL, "messages": CONVERSATION, "stream": False},
    )
    assert response.status_code == 200, response.text
    assert captured["model"] == KLLM_MODEL
    assert response.json()["model"] == KLLM_MODEL
    assert captured["messages"] == CONVERSATION


async def test_switching_providers_preserves_the_same_history(
    client, test_db, gateway_enabled, monkeypatch
):
    """The same stored conversation reaches both providers unchanged."""
    await _seed_managed_provider(test_db)
    seen: dict[str, list[dict[str, str]]] = {}

    async def fake_kllm_ensure(_db, _model):
        return _kllm_model()

    async def fake_hosted_ensure(_db, _key):
        return HostedModel(key=HOSTED_KEY, model=HOSTED_MODEL, context_window=8192, ready=True)

    async def fake_kllm_complete(model, messages, **_kwargs):
        seen["kllm"] = messages
        return "ok", 1, 1

    async def fake_hosted_complete(model, messages, **_kwargs):
        seen["hosted"] = messages
        return "ok", 1, 1

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_kllm_ensure)
    monkeypatch.setattr(hosted, "ensure_model_ready", fake_hosted_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_kllm_complete)
    monkeypatch.setattr(llm_service, "complete_hosted", fake_hosted_complete)

    assert client.post(
        "/api/v1/chat/completions",
        json={"model": KLLM_MODEL, "messages": CONVERSATION, "stream": False},
    ).status_code == 200
    assert client.post(
        "/api/v1/chat/completions",
        json={"model": HOSTED_KEY, "messages": CONVERSATION, "stream": False},
    ).status_code == 200

    assert seen["kllm"] == seen["hosted"]
    assert seen["kllm"] == CONVERSATION


async def test_request_provider_assertion_cannot_change_the_model(
    client, test_db, gateway_enabled, monkeypatch
):
    async def fake_ensure(_db, _model):
        return _kllm_model()

    async def fake_complete(_model, _messages, **_kwargs):
        return "ok", 1, 1

    monkeypatch.setattr(kllm_service, "ensure_model_ready", fake_ensure)
    monkeypatch.setattr(llm_service, "complete_managed", fake_complete)

    response = client.post(
        "/api/v1/chat/completions",
        json={
            "model": KLLM_MODEL,
            "provider": "hosted-ollama",
            "messages": CONVERSATION,
            "stream": False,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "provider_mismatch"
