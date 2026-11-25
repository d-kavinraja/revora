"""Cross-layer parity for the context budget.

The frontend mirrors the backend's output-budget arithmetic so the context
meter describes the request that will actually be sent. The two implementations
live in different languages, so this test pins the shared golden table on the
backend side and checks that the frontend test still declares exactly the same
rows. A change to either implementation without the other fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.chat_service import resolve_max_tokens

FRONTEND_TEST = (
    Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'lib' / 'chat-state.test.mjs'
)

# window -> expected budget for one 3000-character (1000-token) user message.
GOLDEN = [
    (None, 4096),
    (2000, 500),
    (8000, 2000),
    (32000, 4096),
    (128000, 4096),
    (200000, 4096),
]


@pytest.mark.parametrize(('window', 'expected'), GOLDEN)
def test_backend_budget_matches_the_shared_golden_table(window, expected):
    messages = [{'role': 'user', 'content': 'x' * 3000}]
    assert resolve_max_tokens(None, window, messages) == expected


def test_a_tiny_prompt_keeps_the_minimum_reserve():
    assert resolve_max_tokens(None, 2000, [{'role': 'user', 'content': 'hi'}]) == 1024


def test_an_override_is_clamped_to_the_window_and_the_ceiling():
    assert resolve_max_tokens(60_000, None, []) == 16_384
    assert resolve_max_tokens(60_000, 2000, [{'role': 'user', 'content': 'x' * 3000}]) == 500
    assert resolve_max_tokens(0, None, []) == 1


def test_the_frontend_declares_the_same_golden_rows():
    if not FRONTEND_TEST.is_file():
        pytest.skip('frontend test file is not present in this checkout')
    text = FRONTEND_TEST.read_text(encoding='utf-8')
    for window, expected in GOLDEN:
        js_window = 'null' if window is None else str(window)
        row = f'[{js_window}, {expected}],'
        assert row in text, f'frontend golden row missing or changed: {row}'
    assert 'resolveRequestOutputTokens' in text