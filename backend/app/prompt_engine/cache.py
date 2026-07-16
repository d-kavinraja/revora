"""Prompt-level caching.

Caches compiled prompts to avoid redundant rebuilds. Supports memory and Redis.
"""

import time
import logging
import hashlib
import json
from typing import Optional, Any
from collections import OrderedDict

from app.prompt_engine.models import CompiledPrompt

logger = logging.getLogger(__name__)


class PromptCache:
    """In-memory prompt cache with TTL support."""

    def __init__(self, max_size: int = 100, default_ttl: int = 300):
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0

    async def get(self, cache_key: str) -> Optional[CompiledPrompt]:
        """Get a cached prompt by cache key."""
        if cache_key not in self._cache:
            self._misses += 1
            return None

        entry = self._cache[cache_key]
        if time.time() > entry["expires_at"]:
            del self._cache[cache_key]
            self._misses += 1
            return None

        self._hits += 1
        self._cache.move_to_end(cache_key)
        return entry["prompt"]

    async def set(self, cache_key: str, prompt: CompiledPrompt, ttl: Optional[int] = None) -> None:
        """Cache a compiled prompt."""
        if ttl is None:
            ttl = self._default_ttl

        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)

        self._cache[cache_key] = {
            "prompt": prompt,
            "expires_at": time.time() + ttl,
            "created_at": time.time(),
        }

    async def invalidate(self, cache_key: str) -> bool:
        """Invalidate a cached prompt."""
        if cache_key in self._cache:
            del self._cache[cache_key]
            return True
        return False

    async def clear(self) -> None:
        """Clear all cached prompts."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
            "size": len(self._cache),
            "max_size": self._max_size,
        }


def build_cache_key(
    review_type: str,
    repo_id: str,
    diff_content: str,
    provider: str,
    model: str,
    token_budget: int,
) -> str:
    """Build a deterministic cache key from request parameters."""
    content = f"{review_type}:{repo_id}:{diff_content}:{provider}:{model}:{token_budget}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


prompt_cache = PromptCache()
