import time
import asyncio
import logging
from collections import OrderedDict
from typing import Optional, Any

from app.cache.base_cache import BaseCache

logger = logging.getLogger(__name__)


class MemoryCache(BaseCache):
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Optional[Any]:
        if key not in self._store:
            self._misses += 1
            return None

        value, expiry = self._store[key]
        if expiry is not None and time.time() > expiry:
            del self._store[key]
            self._misses += 1
            return None

        self._store.move_to_end(key)
        self._hits += 1
        return value

    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expiry = time.time() + ttl if ttl is not None else None

        if key in self._store:
            self._store.move_to_end(key)
        elif len(self._store) >= self._max_size:
            self._store.popitem(last=False)

        self._store[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def clear(self) -> None:
        self._store.clear()
        self._hits = 0
        self._misses = 0

    async def get_or_compute(
        self, key: str, compute_fn, ttl_seconds: Optional[int] = None
    ) -> Any:
        cached = await self.get(key)
        if cached is not None:
            return cached

        value = await compute_fn() if asyncio.iscoroutinefunction(compute_fn) else compute_fn()
        await self.set(key, value, ttl_seconds)
        return value

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def size(self) -> int:
        return len(self._store)


memory_cache = MemoryCache(max_size=5000, default_ttl=300)
