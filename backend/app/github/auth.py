import jwt
import time
import httpx
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict
from app.core.config import settings

class GitHubAppAuth:
    def __init__(self):
        self.app_id = settings.GITHUB_APP_ID
        self.private_key = settings.GITHUB_APP_PRIVATE_KEY
        self._token_cache: Dict[int, Tuple[str, datetime]] = {}

    def _create_app_jwt(self) -> str:
        """Create a JWT to authenticate as the GitHub App."""
        if not self.app_id or not self.private_key:
            raise ValueError("GitHub App ID or Private Key is missing.")

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": self.app_id,
        }
        key = self.private_key
        if "\\n" in key:
            key = key.replace("\\n", "\n")
        return jwt.encode(payload, key, algorithm="RS256")

    async def get_installation_token(self, installation_id: int) -> str:
        """Get or create an installation access token."""
        # Check cache
        if installation_id in self._token_cache:
            token, expires_at = self._token_cache[installation_id]
            if expires_at > datetime.utcnow() + timedelta(minutes=5):
                return token

        app_jwt = self._create_app_jwt()
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            data = response.json()

        token = data["token"]
        # Handle ISO format parsing
        expires_str = data["expires_at"].replace("Z", "+00:00")
        expires_at = datetime.fromisoformat(expires_str).replace(tzinfo=None)

        self._token_cache[installation_id] = (token, expires_at)
        return token

github_app_auth = GitHubAppAuth()
