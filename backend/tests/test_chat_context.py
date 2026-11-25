"""Payload-level tests for model-aware context fitting.

No test contacts a provider, loads a model, or performs inference: every
assertion is made against pure functions or the request model.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.chat import ChatCompletionRequest
from app.services.chat_service import (
    CHARS_PER_TOKEN_FIT,
    CLIP_MARKER,
    MAX_CONTEXT_CHARS,
    MAX_OUTPUT_TOKENS,
    MIN_INPUT_TOKENS,
    OUTPUT_CONTEXT_RESERVE,
    clamp_requested_max_tokens,
    clip_to_budget,
    hosted_output_reserve,
    max_output_tokens_for_window,
    output_safety_headroom,
    MAX_CONTEXT_CHARS_GLOBAL,
    MAX_CONTEXT_MESSAGES_GLOBAL,
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    MAX_OUTPUT_TOKENS,
    MAX_REQUEST_CHARS,
    MAX_REQUEST_MESSAGES,
    OUTPUT_CONTEXT_RESERVE,
    context_fit_budget,
    trim_chat_context,
)


def _conversation(turns: int, *, chars: int = 10) -> list[dict[str, str]]:
    """``turns`` user/assistant pairs followed by one final user question."""
    messages: list[dict[str, str]] = []
    for index in range(turns):
        messages.append({"role": "user", "content": f"q{index} " + "x" * chars})
        messages.append({"role": "assistant", "content": f"a{index} " + "y" * chars})
    messages.append({"role": "user", "content": "final question"})
    return messages


def _total_chars(messages: list[dict[str, str]]) -> int:
    return sum(len(message["content"]) for message in messages)


# --- budget ---------------------------------------------------------------


def test_unknown_window_keeps_the_legacy_budget():
    assert context_fit_budget(None, None) == (MAX_MESSAGES, MAX_CONTEXT_CHARS)
    assert context_fit_budget(0, None) == (MAX_MESSAGES, MAX_CONTEXT_CHARS)


def test_known_window_derives_a_window_budget():
    max_messages, max_chars = context_fit_budget(8192, None)
    assert max_messages == MAX_CONTEXT_MESSAGES_GLOBAL
    expected_tokens = 8192 - (8192 // 4) - OUTPUT_CONTEXT_RESERVE
    assert max_chars == expected_tokens * CHARS_PER_TOKEN_FIT


def test_window_budget_is_capped_by_the_global_character_limit():
    _, max_chars = context_fit_budget(1_000_000, None)
    assert max_chars == MAX_CONTEXT_CHARS_GLOBAL


def test_explicit_output_reserve_reduces_the_input_budget():
    _, max_chars = context_fit_budget(131_072, MAX_OUTPUT_TOKENS)
    assert max_chars == (131_072 - MAX_OUTPUT_TOKENS - OUTPUT_CONTEXT_RESERVE) * CHARS_PER_TOKEN_FIT
    _, with_default = context_fit_budget(131_072, None)
    # 131072 // 4 = 32768 is clamped to MAX_OUTPUT_TOKENS, so the default reserve
    # equals an explicit MAX_OUTPUT_TOKENS override.
    assert with_default == max_chars


# --- trimming -------------------------------------------------------------


def test_windowed_fit_sends_more_than_twenty_messages():
    messages = _conversation(60)
    fitted = trim_chat_context(messages, context_window=131_072)
    assert len(fitted) > MAX_MESSAGES
    assert len(fitted) == len(messages)
    assert fitted[-1]["content"] == "final question"
    assert fitted[0]["role"] == "user"


def test_small_window_fits_oldest_first_and_keeps_the_latest_turn():
    messages = _conversation(30, chars=1000)
    fitted = trim_chat_context(messages, context_window=8192)
    _, max_chars = context_fit_budget(8192, None)
    assert 0 < len(fitted) < len(messages)
    assert _total_chars(fitted) <= max_chars
    assert fitted[0]["role"] == "user"
    assert fitted[-1] == {"role": "user", "content": "final question"}


def test_unknown_window_still_applies_the_fixed_cap():
    messages = _conversation(60)
    fitted = trim_chat_context(messages)
    assert len(fitted) <= MAX_MESSAGES
    assert _total_chars(fitted) <= MAX_CONTEXT_CHARS
    assert fitted[-1]["content"] == "final question"
    assert fitted[0]["role"] == "user"


def test_newest_turn_keeps_its_head_and_tail_when_it_alone_overflows():
    instruction = "INSTRUCTION: summarise the trace below."
    tail = "END-OF-TRACE"
    messages = [{"role": "user", "content": f"{instruction}{'x' * 20_000}{tail}"}]
    fitted = trim_chat_context(messages, context_window=4096)
    _, max_chars = context_fit_budget(4096, None)
    assert len(fitted) == 1
    content = fitted[0]["content"]
    assert len(content) <= max_chars
    # The instruction at the front survives; the end of the paste survives too.
    assert content.startswith(instruction)
    assert content.endswith(tail)
    assert content.count(CLIP_MARKER) == 1
    # Clipping is outbound only: the caller's message is untouched.
    assert messages[0]["content"].endswith(tail)
    assert len(messages[0]["content"]) == len(instruction) + 20_000 + len(tail)
    # Refitting an already clipped turn never adds a second marker.
    again = trim_chat_context([{"role": "user", "content": content}], context_window=4096)
    assert again[0]["content"] == content


def test_clipping_keeps_the_beginning_when_no_marker_fits():
    clipped = clip_to_budget("abcdefghijklmnopqrstuvwxyz", 10)
    assert clipped == "abcdefghij"
    assert CLIP_MARKER not in clipped


def test_headroom_and_output_ceiling_shrink_with_the_window():
    assert output_safety_headroom(None) == OUTPUT_CONTEXT_RESERVE
    assert output_safety_headroom(8192) == OUTPUT_CONTEXT_RESERVE
    assert output_safety_headroom(4096) == 1024
    assert output_safety_headroom(2048) == 512
    assert max_output_tokens_for_window(8192) == 8192 - 2048 - MIN_INPUT_TOKENS
    assert max_output_tokens_for_window(None) == MAX_OUTPUT_TOKENS
    assert max_output_tokens_for_window(131_072) == MAX_OUTPUT_TOKENS


def test_a_client_override_is_clamped_so_a_prompt_still_fits():
    assert clamp_requested_max_tokens(None, 8192) is None
    assert clamp_requested_max_tokens(MAX_OUTPUT_TOKENS, 8192) == max_output_tokens_for_window(8192)
    assert clamp_requested_max_tokens(MAX_OUTPUT_TOKENS, None) == MAX_OUTPUT_TOKENS
    assert clamp_requested_max_tokens(2048, 8192) == 2048
    assert clamp_requested_max_tokens(0, 8192) == 1


def test_the_fit_budget_never_spends_more_than_the_window():
    # prompt + reserved output + headroom == window, exactly, at the fit cap.
    for window in (2048, 4096, 8192, 32_768, 131_072):
        _, max_chars = context_fit_budget(window, None)
        reserve = hosted_output_reserve(None, window)
        headroom = output_safety_headroom(window)
        assert max_chars // CHARS_PER_TOKEN_FIT == window - reserve - headroom
        assert reserve >= 1
        assert window - reserve - headroom >= 0


def test_an_explicit_reserve_also_fits_inside_the_window():
    for window in (4096, 8192, 131_072):
        requested = MAX_OUTPUT_TOKENS
        _, max_chars = context_fit_budget(window, requested)
        reserve = hosted_output_reserve(requested, window)
        assert reserve == max_output_tokens_for_window(window)
        assert max_chars // CHARS_PER_TOKEN_FIT + reserve + output_safety_headroom(window) <= window


def test_fitting_does_not_mutate_the_caller_messages():
    messages = _conversation(30, chars=1000)
    snapshot = copy.deepcopy(messages)
    trim_chat_context(messages, context_window=8192)
    assert messages == snapshot


def test_leading_assistant_turns_are_never_sent():
    messages = [
        {"role": "assistant", "content": "orphan answer"},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "follow up"},
    ]
    fitted = trim_chat_context(messages, context_window=131_072)
    assert fitted[0] == {"role": "user", "content": "question"}


def test_strict_alternation_merges_after_window_fitting():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "third"},
    ]
    fitted = trim_chat_context(messages, strict_alternation=True, context_window=131_072)
    assert [m["role"] for m in fitted] == ["user", "assistant", "user"]
    assert fitted[0]["content"] == "first\n\nsecond"
    assert "third" in fitted[2]["content"]


def test_kllm_keeps_consecutive_same_role_turns():
    messages = [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
    ]
    fitted = trim_chat_context(messages, context_window=131_072)
    assert [m["role"] for m in fitted] == ["user", "user"]


def test_secrets_are_redacted_in_every_historical_turn():
    messages = [
        {"role": "user", "content": "key sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
        {"role": "assistant", "content": "noted"},
        {"role": "user", "content": "and again sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    ]
    fitted = trim_chat_context(messages, context_window=131_072)
    assert all("sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in m["content"] for m in fitted)
    assert any("[REDACTED]" in m["content"] for m in fitted)


# --- request validation ---------------------------------------------------


def test_request_model_accepts_a_long_conversation():
    request = ChatCompletionRequest(
        model="qwen3.8-27b",
        messages=_conversation(60),
        stream=False,
    )
    assert len(request.messages) == 121


def test_request_model_rejects_more_than_the_global_message_cap():
    messages = [{"role": "user", "content": "hi"}] * (MAX_REQUEST_MESSAGES + 1)
    with pytest.raises(ValidationError):
        ChatCompletionRequest(model="qwen3.8-27b", messages=messages, stream=False)


def test_request_model_rejects_an_oversized_total():
    # Each turn is legal on its own; together they exceed the request ceiling.
    count = (MAX_REQUEST_CHARS // MAX_MESSAGE_CHARS) + 1
    messages = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": "x" * MAX_MESSAGE_CHARS}
        for index in range(count)
    ]
    messages.append({"role": "user", "content": "final"})
    assert sum(len(m["content"]) for m in messages) > MAX_REQUEST_CHARS
    with pytest.raises(ValidationError):
        ChatCompletionRequest(model="qwen3.8-27b", messages=messages, stream=False)
