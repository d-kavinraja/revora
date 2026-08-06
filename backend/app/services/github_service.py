"""GitHubService — real-time GitHub API access with caching.

Provides PR state lookups used by lifecycle validation.
All responses are cached for 60 seconds to reduce GitHub API calls.
"""

import logging
from typing import Any

import httpx

from app.cache.memory_cache import memory_cache
from app.github.auth import github_app_auth

logger = logging.getLogger(__name__)

PR_CACHE_TTL = 60  # seconds


class GitHubService:
    """Service for fetching real-time pull request data from GitHub."""

    async def get_pull_request(
        self,
        repo_full_name: str,
        pr_number: int,
        installation_id: int,
    ) -> dict[str, Any]:
        """Fetch the latest PR state from the GitHub API.

        Returns a dict with keys:
          state, merged, draft, title, head_sha, base_branch, head_branch

        Results are cached for PR_CACHE_TTL seconds.
        """
        cache_key = f"github:pr:{repo_full_name}:{pr_number}"

        cached = await memory_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            token = await github_app_auth.get_installation_token(installation_id)
            url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                response.raise_for_status()
                data = response.json()

            state = data.get("state", "unknown")
            merged = data.get("merged", False)

            result = {
                "state": "merged" if merged else state,
                "merged": merged,
                "draft": data.get("draft", False),
                "title": data.get("title", ""),
                "head_sha": data.get("head", {}).get("sha", ""),
                "base_branch": data.get("base", {}).get("ref", ""),
                "head_branch": data.get("head", {}).get("ref", ""),
            }

            await memory_cache.set(cache_key, result, ttl_seconds=PR_CACHE_TTL)
            return result

        except httpx.HTTPStatusError as e:
            logger.warning(
                f"GitHub API error fetching PR {repo_full_name}#{pr_number}: {e}"
            )
            return {"state": "unknown", "error": str(e)}
        except Exception as e:
            logger.error(
                f"Failed to fetch PR {repo_full_name}#{pr_number}: {e}",
                exc_info=True,
            )
            return {"state": "unknown", "error": str(e)}

    async def batch_get_pull_requests(
        self,
        prs: list[tuple[str, int, int]],
    ) -> dict[str, dict[str, Any]]:
        """Fetch multiple PRs, returning {repo_full_name:#pr_number: result}.

        Each tuple: (repo_full_name, pr_number, installation_id).
        Reuses the per-PR cache.
        """
        result: dict[str, dict[str, Any]] = {}
        for repo_full_name, pr_number, installation_id in prs:
            key = f"{repo_full_name}#{pr_number}"
            result[key] = await self.get_pull_request(
                repo_full_name, pr_number, installation_id
            )
        return result

    async def invalidate_pr_cache(self, repo_full_name: str, pr_number: int) -> None:
        """Drop the cached PR state so the next request fetches fresh data.

        Called from webhook handlers (opened/reopened/synchronize/closed) so
        badge and state updates propagate immediately instead of waiting for
        the PR_CACHE_TTL window to expire.
        """
        cache_key = f"github:pr:{repo_full_name}:{pr_number}"
        await memory_cache.delete(cache_key)


github_service = GitHubService()
