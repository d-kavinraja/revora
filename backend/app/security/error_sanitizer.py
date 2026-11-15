"""Shared sanitization for error messages crossing trust boundaries.

Provider/HTTP exceptions regularly embed request URLs, headers, and API keys.
Apply this helper before an exception string reaches a client response, a
persisted error column, or an audit-facing surface. Full detail stays in the
server logs.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"gsk_[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"xai-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"nvapi-[A-Za-z0-9_\-./+]{4,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-./+=]+", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[:=]\s*['\"]?[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*['\"]?[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"password\s*[:=]\s*['\"]?[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"]+"),
)

MAX_ERROR_MESSAGE_LENGTH = 300


def sanitize_error_message(message: object) -> str:
    """Strip credentials/URLs from an error message and bound its length."""
    cleaned = str(message) if message is not None else ""
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    return cleaned[:MAX_ERROR_MESSAGE_LENGTH]
