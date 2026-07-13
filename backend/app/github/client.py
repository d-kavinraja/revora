import httpx
from typing import List, Dict, Any, Optional

from app.github.auth import github_app_auth

class GitHubClient:
    """Client for interacting with the GitHub API."""
    
    async def _get_headers(self, installation_id: int) -> Dict[str, str]:
        token = await github_app_auth.get_installation_token(installation_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def create_check_run(
        self, installation_id: int, owner: str, repo: str, name: str, head_sha: str, status: str = "in_progress", output: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Creates a check run on a GitHub commit."""
        headers = await self._get_headers(installation_id)
        url = f"https://api.github.com/repos/{owner}/{repo}/check-runs"
        
        payload = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
        }
        
        if output:
            payload["output"] = output
            if status == "completed":
                payload["conclusion"] = output.get("conclusion", "success")

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
            
    async def update_check_run(
        self, installation_id: int, owner: str, repo: str, check_run_id: int, status: str, output: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Updates an existing check run."""
        headers = await self._get_headers(installation_id)
        url = f"https://api.github.com/repos/{owner}/{repo}/check-runs/{check_run_id}"
        
        payload = {"status": status}
        if output:
            payload["output"] = output
            if status == "completed":
                payload["conclusion"] = output.get("conclusion", "success")

        async with httpx.AsyncClient() as client:
            response = await client.patch(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def create_pr_review(
        self, installation_id: int, owner: str, repo: str, pull_number: int, body: str, event: str = "COMMENT", comments: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Submit a full PR review with summary and optional inline comments."""
        headers = await self._get_headers(installation_id)
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}/reviews"
        
        payload = {
            "body": body,
            "event": event, # Can be APPROVE, REQUEST_CHANGES, or COMMENT
        }
        
        if comments:
            payload["comments"] = comments

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

github_client = GitHubClient()
