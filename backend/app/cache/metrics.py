import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CacheMetrics:
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    total_latency_ms: float = 0.0
    error_count: int = 0
    operation_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        total_ops = self.hits + self.misses + self.sets + self.deletes
        return self.total_latency_ms / total_ops if total_ops > 0 else 0.0

    def record_hit(self, latency_ms: float) -> None:
        self.hits += 1
        self.total_latency_ms += latency_ms
        self.operation_counts["get"] += 1

    def record_miss(self, latency_ms: float) -> None:
        self.misses += 1
        self.total_latency_ms += latency_ms
        self.operation_counts["get"] += 1

    def record_set(self, latency_ms: float) -> None:
        self.sets += 1
        self.total_latency_ms += latency_ms
        self.operation_counts["set"] += 1

    def record_delete(self, latency_ms: float) -> None:
        self.deletes += 1
        self.total_latency_ms += latency_ms
        self.operation_counts["delete"] += 1

    def record_error(self) -> None:
        self.error_count += 1

    def snapshot(self) -> dict:
        return {
            "hit_rate": round(self.hit_rate, 3),
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "deletes": self.deletes,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "error_count": self.error_count,
            "operations": dict(self.operation_counts),
        }

    def reset(self) -> None:
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.deletes = 0
        self.total_latency_ms = 0.0
        self.error_count = 0
        self.operation_counts.clear()


graph_cache_metrics = CacheMetrics()
retrieval_cache_metrics = CacheMetrics()
knowledge_cache_metrics = CacheMetrics()
