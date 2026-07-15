import pytest
from app.cache.memory_cache import MemoryCache, memory_cache
from app.cache.base_cache import BaseCache


@pytest.fixture
async def cache():
    c = MemoryCache(max_size=100, default_ttl=10)
    yield c
    await c.clear()


class TestMemoryCache:
    async def test_set_and_get(self, cache):
        await cache.set("key1", "value1")
        result = await cache.get("key1")
        assert result == "value1"

    async def test_get_missing_key(self, cache):
        result = await cache.get("nonexistent")
        assert result is None

    async def test_delete(self, cache):
        await cache.set("key1", "value1")
        await cache.delete("key1")
        result = await cache.get("key1")
        assert result is None

    async def test_exists(self, cache):
        await cache.set("key1", "value1")
        assert await cache.exists("key1") is True
        await cache.delete("key1")
        assert await cache.exists("key1") is False

    async def test_clear(self, cache):
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None

    async def test_ttl_expiry(self):
        cache = MemoryCache(max_size=100, default_ttl=0)
        await cache.set("key1", "value1", ttl_seconds=0)
        import time
        time.sleep(0.1)
        result = await cache.get("key1")
        assert result is None

    async def test_max_size_eviction(self):
        cache = MemoryCache(max_size=3, default_ttl=60)
        for i in range(5):
            await cache.set(f"key{i}", f"value{i}")
        assert cache.size <= 3

    async def test_get_or_compute(self, cache):
        computed = False

        async def compute_fn():
            nonlocal computed
            computed = True
            return "computed_value"

        result1 = await cache.get_or_compute("key1", compute_fn)
        assert result1 == "computed_value"
        assert computed is True

        computed = False
        result2 = await cache.get_or_compute("key1", compute_fn)
        assert result2 == "computed_value"
        assert computed is False

    async def test_hit_rate(self, cache):
        await cache.get("miss1")
        await cache.get("miss2")
        await cache.set("hit1", "v1")
        await cache.get("hit1")
        assert cache.hit_rate > 0

    async def test_empty_cache_hit_rate(self, cache):
        assert cache.hit_rate == 0.0

    async def test_large_values(self, cache):
        large = "x" * 100000
        await cache.set("large", large)
        result = await cache.get("large")
        assert result == large

    async def test_dict_values(self, cache):
        data = {"name": "test", "values": [1, 2, 3], "nested": {"a": 1}}
        await cache.set("dict", data)
        result = await cache.get("dict")
        assert result == data

    async def test_delete_nonexistent(self, cache):
        await cache.delete("nonexistent")
        assert True

    async def test_update_existing(self, cache):
        await cache.set("key", "old")
        await cache.set("key", "new")
        result = await cache.get("key")
        assert result == "new"
