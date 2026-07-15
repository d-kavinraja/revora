from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.ranking.base_scorer import BaseScorer
from app.indexing.models import RepositoryIndex

SECURITY_KEYWORDS = [
    "auth", "login", "password", "token", "jwt", "oauth",
    "permission", "role", "rbac", "cors", "csrf", "xss",
    "injection", "sanitize", "encrypt", "decrypt", "hash",
    "secret", "ssl", "tls", "https", "certificate",
    "rate.limit", "throttle", "firewall", "audit",
    "validator", "middleware", "guard",
]


class SecurityImpactScorer(BaseScorer):
    @property
    def name(self) -> str:
        return "security_impact"

    @property
    def weight(self) -> float:
        return 0.15

    async def score(
        self,
        context: RetrievedContext,
        index: Optional[RepositoryIndex] = None,
    ) -> float:
        file_path = context.file_path
        content_lower = context.content.lower()

        matches = sum(1 for kw in SECURITY_KEYWORDS if kw in file_path.lower())
        content_matches = sum(1 for kw in SECURITY_KEYWORDS if kw in content_lower)

        if matches > 0 or content_matches > 5:
            return min(1.0, 0.5 + (matches * 0.1) + (min(content_matches, 20) * 0.02))

        return 0.3
