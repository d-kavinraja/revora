"""Queue and cache detection engine.

Detects message queues and caching solutions.
Uses the shared RepoWalker for efficient filesystem access.
"""

from typing import List

from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.core.constants import MAX_FILES_PER_DETECTOR


QUEUE_SIGNATURES = {
    "celery": ["celery", "Celery"],
    "rq": ["rq", "redis-queue"],
    "bull": ["bull", "Bull"],
    "sidekiq": ["sidekiq", "Sidekiq"],
    "kafka": ["kafka", "Kafka", "kafkajs"],
    "rabbitmq": ["rabbitmq", "RabbitMQ", "pika", "amqp"],
    "sqs": ["sqs", "SQS"],
    "pubsub": ["pubsub", "PubSub"],
    "redis_queue": ["redis_queue", "RedisQueue"],
}

CACHE_SIGNATURES = {
    "redis": ["redis", "Redis", "aioredis"],
    "memcached": ["memcached", "Memcached", "pymemcache"],
    "local_cache": ["functools.lru_cache", "@cache", "lru_cache"],
    "disk_cache": ["diskcache", "DiskCache"],
}


class QueueDetector(BaseDetector):
    """Detects message queues and caching solutions."""

    @property
    def name(self) -> str:
        return "queue_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect queues and caches using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with queue and cache info.
        """
        queues: List[str] = []
        caching: List[str] = []

        # Collect file content for analysis
        config_files = [
            fp for fp in walker.file_paths
            if any(fp.endswith(ext) for ext in [
                ".py", ".js", ".ts", ".tsx", ".jsx",
                ".go", ".java", ".rb", ".php",
                ".yaml", ".yml", ".json", ".toml",
            ])
        ]

        all_content = ""
        files_checked = 0

        for fp in config_files:
            if files_checked >= MAX_FILES_PER_DETECTOR:
                break
            content = await walker.get_content(fp, max_chars=2000)
            if content:
                all_content += content + "\n"
                files_checked += 1

        # Detect queues
        for queue_name, signatures in QUEUE_SIGNATURES.items():
            for sig in signatures:
                if sig in all_content:
                    if queue_name not in queues:
                        queues.append(queue_name)
                    break

        # Detect caching
        for cache_name, signatures in CACHE_SIGNATURES.items():
            for sig in signatures:
                if sig in all_content:
                    if cache_name not in caching:
                        caching.append(cache_name)
                    break

        return DetectorResult(
            success=True,
            data={
                "queues": queues,
                "caching": caching,
            },
            confidence=0.7 if queues or caching else 0.0,
        )


# Legacy function interface for backward compatibility
def detect_queues(repo_path: str) -> List[str]:
    """Detect queues in a repository (legacy interface)."""
    import asyncio
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = QueueDetector()
        result = await detector.detect(walker)
        return result.data.get("queues", [])

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _detect()).result()
        else:
            return loop.run_until_complete(_detect())
    except RuntimeError:
        return asyncio.run(_detect())


def detect_caching(repo_path: str) -> List[str]:
    """Detect caching in a repository (legacy interface)."""
    import asyncio
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = QueueDetector()
        result = await detector.detect(walker)
        return result.data.get("caching", [])

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _detect()).result()
        else:
            return loop.run_until_complete(_detect())
    except RuntimeError:
        return asyncio.run(_detect())
