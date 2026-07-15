import time
import hashlib
import logging
from typing import Optional

from app.cache.redis_cache import redis_cache
from app.cache.memory_cache import memory_cache

logger = logging.getLogger(__name__)


class RetrievalCache:
    def __init__(self, default_ttl: int = 300):
        self._default_ttl = default_ttl

    async def get(
        self,
        repo_id: str,
        changed_files_hash: str,
        budget: int,
    ) -> Optional[dict]:
        key = self._build_key(repo_id, changed_files_hash, budget)
        return await redis_cache.get(key)

    async def set(
        self,
        repo_id: str,
        changed_files_hash: str,
        budget: int,
        result: dict,
        ttl: Optional[int] = None,
    ) -> None:
        key = self._build_key(repo_id, changed_files_hash, budget)
        await redis_cache.set(key, result, ttl or self._default_ttl)

    async def invalidate(self, repo_id: str) -> None:
        pattern = f"cache:retrieval:{repo_id}:*"
        try:
            await redis_cache.delete(pattern)
        except Exception:
            pass

    def _build_key(self, repo_id: str, changed_files_hash: str, budget: int) -> str:
        raw = f"retrieval:{repo_id}:{changed_files_hash}:{budget}"
        return f"cache:retrieval:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


retrieval_cache = RetrievalCache()
