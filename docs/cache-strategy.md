# Caching Strategy

Revora uses a multi-layered caching system to reduce redundant computation, speed up repeated retrievals, and lower LLM costs.

## Cache Layers

| Layer | Backend | TTL | Purpose |
|-------|---------|-----|---------|
| `MemoryCache` | In-process dict (LRU) | Configurable (default 300s) | Hot cache for frequently accessed data |
| `RedisCache` | Redis 7 | Configurable (default 3600s) | Distributed cache for multi-worker deployments |
| `GraphCache` | Memory + optional Redis | 600s | Caches graph traversal results (BFS, DFS, shortest path, k-hop) |
| `RetrievalCache` | Memory + optional Redis | Varies by content | Caches final retrieval results keyed by query hash |
| `KnowledgeCache` | PostgreSQL + Memory | 3600s | Caches knowledge base lookups |

## MemoryCache

An LRU (Least Recently Used) eviction cache for single-process deployments:

```python
from app.cache.memory_cache import MemoryCache

cache = MemoryCache(maxsize=1000, ttl=300)
await cache.set("key", {"data": "value"})
result = await cache.get("key")
```

## RedisCache

A Redis-backed cache for distributed deployments:

```python
from app.cache.redis_cache import RedisCache

cache = RedisCache(
    redis_url="redis://localhost:6379/0",
    ttl=3600,
    prefix="revora:cache:",
)
await cache.set("key", {"data": "value"})
result = await cache.get("key")
```

## Cache Selection

The cache layer auto-selects between Memory and Redis based on configuration:

```python
from app.cache.base_cache import create_cache

cache = create_cache(
    backend="redis" if redis_available else "memory",
    redis_url="redis://localhost:6379/0",
    ttl=300,
)
```

## Graph Cache

Caches expensive graph traversal operations:

```python
from app.cache.graph_cache import GraphCache

graph_cache = GraphCache(cache)
# Caches BFS, DFS, shortest_path, k_hop, reachable_nodes

# Invalidated when graph is rebuilt
await graph_cache.invalidate(repo_id)
```

## Retrieval Cache

Caches the final output of the retrieval pipeline:

```python
from app.cache.retrieval_cache import RetrievalCache

retrieval_cache = RetrievalCache(cache)
# Keyed by hash(changed_files + repo_id + budget_config)
# Auto-invalidated when files change
```

## Metrics

All cache operations are tracked via `CacheMetrics`:

| Metric | Description |
|--------|-------------|
| `hits` | Number of cache hits |
| `misses` | Number of cache misses |
| `hit_ratio` | hits / (hits + misses) |
| `size` | Current number of cache entries |
| `evictions` | Number of evictions (LRU) |
| `avg_lookup_time` | Average lookup time in ms |

```python
from app.cache.metrics import CacheMetrics

metrics = CacheMetrics()
metrics.record_hit()
metrics.record_miss()
print(metrics.hit_ratio)  # 0.0 - 1.0
```

## Testing

```bash
cd backend
python -m pytest tests/test_cache.py -v
```
