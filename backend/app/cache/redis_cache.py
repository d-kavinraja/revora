import json
import logging
from typing import Optional, Any

from app.cache.base_cache import BaseCache
from app.cache.memory_cache import memory_cache

logger = logging.getLogger(__name__)


class RedisCache(BaseCache):
    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url
        self._client = None
        self._available = False

    async def _ensure_client(self):
        if self._client is not None:
            return self._client is not None
        if not self._redis_url:
            self._available = False
            return False
        try:
            import redis.asyncio as aioredis
            self._client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            await self._client.ping()
            self._available = True
            logger.info("Redis cache connected")
            return True
        except Exception as e:
            logger.warning(f"Redis unavailable, falling back to memory cache: {e}")
            self._client = None
            self._available = False
            return False

    async def get(self, key: str) -> Optional[Any]:
        if not await self._ensure_client():
            return await memory_cache.get(key)
        try:
            value = await self._client.get(key)
            if value is None:
                return None
            return json.loads(value)
        except Exception as e:
            logger.debug(f"Redis get failed: {e}")
            return await memory_cache.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        await memory_cache.set(key, value, ttl_seconds)
        if not await self._ensure_client():
            return
        try:
            serialized = json.dumps(value, default=str)
            if ttl_seconds:
                await self._client.setex(key, ttl_seconds, serialized)
            else:
                await self._client.set(key, serialized)
        except Exception as e:
            logger.debug(f"Redis set failed: {e}")

    async def delete(self, key: str) -> None:
        await memory_cache.delete(key)
        if not await self._ensure_client():
            return
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.debug(f"Redis delete failed: {e}")

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def clear(self) -> None:
        await memory_cache.clear()
        if not await self._ensure_client():
            return
        try:
            await self._client.flushdb()
        except Exception as e:
            logger.debug(f"Redis clear failed: {e}")

    async def get_or_compute(
        self, key: str, compute_fn, ttl_seconds: Optional[int] = None
    ) -> Any:
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await compute_fn() if hasattr(compute_fn, "__await__") else compute_fn()
        await self.set(key, value, ttl_seconds)
        return value


redis_cache = RedisCache()
