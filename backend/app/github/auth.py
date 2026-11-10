"""GitHub App authentication helpers (JWT + installation tokens)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import httpx
import jwt

from app.core.config import settings
from app.github.errors import (
    GitHubConfigurationError,
    GitHubRateLimitedError,
    GitHubReauthorizationRequiredError,
    GitHubTransientError,
    bounded_backoff,
    retry_after_from_headers,
    safe_message,
)


class GitHubAppAuth:
    def __init__(self):
        self._token_cache: dict[tuple[str, int], tuple[str, datetime]] = {}

    @property
    def app_id(self) -> str | None:
        return settings.GITHUB_APP_ID

    @property
    def private_key(self) -> str | None:
        return settings.GITHUB_APP_PRIVATE_KEY

    def _create_app_jwt(self) -> str:
        """Create a JWT to authenticate as the GitHub App."""
        app_id = self.app_id
        private_key = self.private_key

        if not app_id:
            raise GitHubConfigurationError(
                "configuration_error",
                status_code=None,
                retryable=False,
                message="GITHUB_APP_ID is missing in server environment variables.",
            )
        if not private_key:
            raise GitHubConfigurationError(
                "configuration_error",
                status_code=None,
                retryable=False,
                message="GITHUB_APP_PRIVATE_KEY is missing in server environment variables.",
            )

        now = int(time.time())
        # GitHub rejects App JWTs whose exp is more than 10 minutes in the
        # future. Use 8 minutes so a small local/GitHub clock skew still
        # leaves the token valid instead of triggering configuration_error.
        payload = {
            "iat": now - 60,
            "exp": now + (8 * 60),
            "iss": str(app_id),
        }
        key = private_key
        if "\\n" in key:
            key = key.replace("\\n", "\n")
        return jwt.encode(payload, key, algorithm="RS256")

    async def get_installation(self, installation_id: int) -> dict | None:
        """Fetch installation metadata (permissions, suspension) from GitHub.

        Returns None when the installation no longer exists (404). Other HTTP
        failures raise typed errors without response bodies.
        """
        app_jwt = self._create_app_jwt()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"https://api.github.com/app/installations/{installation_id}",
                    headers={
                        "Authorization": f"Bearer {app_jwt}",
                        "Accept": "application/vnd.github+json",
                    },
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GitHubTransientError(
                "transient",
                status_code=None,
                retryable=True,
                message=safe_message(exc),
            ) from exc

        if response.status_code == 404:
            return None
        if response.status_code == 429:
            retry_after = retry_after_from_headers(response.headers)
            raise GitHubRateLimitedError(
                "rate_limited",
                status_code=429,
                retryable=True,
                retry_after=retry_after,
                message="GitHub rate limited installation metadata request.",
            )
        if response.status_code in (401, 403):
            raise GitHubConfigurationError(
                "configuration_error",
                status_code=response.status_code,
                retryable=False,
                message="GitHub rejected the App JWT while fetching installation metadata.",
            )
        if response.status_code >= 500:
            retry_after = retry_after_from_headers(response.headers)
            raise GitHubTransientError(
                "transient",
                status_code=response.status_code,
                retryable=True,
                retry_after=retry_after,
                message="GitHub server error while fetching installation metadata.",
            )
        if not response.is_success:
            raise GitHubTransientError(
                "transient",
                status_code=response.status_code,
                retryable=True,
                message="GitHub installation metadata request failed.",
            )
        return response.json()

    async def get_installation_token(self, installation_id: int) -> str:
        """Get or create an installation access token."""
        cache_key = (str(self.app_id or ""), installation_id)
        cached = self._token_cache.get(cache_key)
        if cached is not None:
            token, expires_at = cached
            if expires_at > datetime.now(UTC) + timedelta(minutes=5):
                return token

        app_jwt = self._create_app_jwt()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                    headers={
                        "Authorization": f"Bearer {app_jwt}",
                        "Accept": "application/vnd.github+json",
                    },
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GitHubTransientError(
                "transient",
                status_code=None,
                retryable=True,
                message=safe_message(exc),
            ) from exc

        if response.is_success:
            data = response.json()
            token = data["token"]
            expires_str = data["expires_at"].replace("Z", "+00:00")
            expires_at = datetime.fromisoformat(expires_str)
            self._token_cache[cache_key] = (token, expires_at)
            return token

        status_code = response.status_code
        retry_after = retry_after_from_headers(response.headers)

        if status_code == 404:
            raise GitHubTransientError(
                "transient_not_found",
                status_code=404,
                retryable=True,
                retry_after=retry_after,
                message="GitHub returned 404 for the installation token.",
            )
        if status_code in (401, 422):
            raise GitHubConfigurationError(
                "configuration_error",
                status_code=status_code,
                retryable=False,
                message="GitHub rejected the App JWT or installation id.",
            )
        if status_code == 403:
            raise GitHubReauthorizationRequiredError(
                "reauthorization_required",
                status_code=403,
                retryable=True,
                retry_after=retry_after,
                message="GitHub refused the installation token request.",
            )
        if status_code == 429:
            raise GitHubRateLimitedError(
                "rate_limited",
                status_code=429,
                retryable=True,
                retry_after=retry_after,
                message="GitHub rate limited the installation token request.",
            )
        if status_code >= 500:
            raise GitHubTransientError(
                "transient",
                status_code=status_code,
                retryable=True,
                retry_after=retry_after,
                message="GitHub server error while creating the installation token.",
            )
        raise GitHubTransientError(
            "transient",
            status_code=status_code,
            retryable=True,
            retry_after=retry_after,
            message="GitHub installation token request failed.",
        )


github_app_auth = GitHubAppAuth()
# Keep the import name stable for callers/tests.
_ = bounded_backoff
