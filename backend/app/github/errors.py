"""Typed, sanitized errors for GitHub App authentication.

These exceptions intentionally avoid logging or carrying tokens, JWTs,
private keys, request headers, or response bodies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class AuthErrorInfo:
    category: str
    status_code: int | None
    retryable: bool
    retry_after: datetime | None = None
    message: str = ""


class GitHubAuthError(Exception):
    """Base class for GitHub App authentication failures."""

    def __init__(
        self,
        category: str,
        *,
        status_code: int | None = None,
        retryable: bool = True,
        retry_after: datetime | None = None,
        message: str = "GitHub authentication failed",
    ):
        self.category = category
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after = retry_after
        self.message = message
        super().__init__(f"{category}: {message}")

    def __str__(self) -> str:
        return self.message


class GitHubConfigurationError(GitHubAuthError):
    pass


class GitHubInaccessibleError(GitHubAuthError):
    pass


class GitHubSuspendedError(GitHubAuthError):
    pass


class GitHubReauthorizationRequiredError(GitHubAuthError):
    pass


class GitHubRateLimitedError(GitHubAuthError):
    pass


class GitHubTransientError(GitHubAuthError):
    pass


def parse_retry_after(value: str | None, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(UTC)
    if not value:
        return None
    value = value.strip()
    try:
        seconds = int(value)
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        except (TypeError, ValueError):
            return None
    if seconds < 0:
        return None
    return now + timedelta(seconds=seconds)


def retry_after_from_headers(headers: Any, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(UTC)
    if not headers:
        return None
    retry_after = getattr(headers, "get", lambda _k: None)("Retry-After")
    parsed = parse_retry_after(retry_after, now)
    if parsed is not None:
        return parsed
    reset = getattr(headers, "get", lambda _k: None)("X-RateLimit-Reset")
    if reset is not None:
        try:
            reset_at = datetime.fromtimestamp(int(reset), tz=UTC)
            if reset_at > now:
                return reset_at
        except (TypeError, ValueError):
            return None
    return None


def bounded_backoff(
    failure_count: int,
    *,
    base_seconds: int,
    max_seconds: int,
    now: datetime | None = None,
) -> datetime:
    now = now or datetime.now(UTC)
    capped = min(max(failure_count, 1), 8)
    delay = min(base_seconds * (2 ** (capped - 1)), max_seconds)
    return now + timedelta(seconds=delay)


def safe_message(exc: Exception) -> str:
    """Return a message without response bodies or secrets."""

    text = str(exc)
    if len(text) > 200:
        text = text[:200]
    return text
