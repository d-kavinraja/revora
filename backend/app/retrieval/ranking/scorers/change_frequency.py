import os
import subprocess
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.ranking.base_scorer import BaseScorer
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)


class ChangeFrequencyScorer(BaseScorer):
    def __init__(self):
        self._cache: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "change_frequency"

    @property
    def weight(self) -> float:
        return 0.10

    async def score(
        self,
        context: RetrievedContext,
        index: Optional[RepositoryIndex] = None,
    ) -> float:
        repo_path = getattr(context, "_repo_path", None)
        if not repo_path:
            return 0.5

        file_path = context.file_path
        cache_key = f"{repo_path}:{file_path}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "log", "--oneline", "--follow", "--since=6 months", "--", file_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            commit_count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0

            score = min(1.0, commit_count / 20.0)
            self._cache[cache_key] = score
            return score
        except Exception:
            return 0.5
