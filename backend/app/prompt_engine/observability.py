"""Prompt observability and metrics tracking.

Tracks prompt generation time, size, tokens, compression ratio, cache hits/misses,
cost estimates, provider, and model.
"""

import time
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass, field

from app.prompt_engine.models import CompiledPrompt, PromptBuildRequest

logger = logging.getLogger(__name__)


@dataclass
class PromptMetricRecord:
    """A single prompt build metric record."""
    prompt_id: str
    review_type: str
    provider: str
    model: str
    total_tokens: int
    prompt_size_bytes: int
    compression_ratio: float
    build_time_ms: float
    cache_hit: bool
    estimated_cost_usd: float
    sections_count: int
    files_included: int
    created_at: float
    metadata: dict = field(default_factory=dict)


class PromptObservability:
    """Tracks prompt build metrics for observability."""

    def __init__(self, max_records: int = 1000):
        self._records: List[PromptMetricRecord] = []
        self._max_records = max_records

    async def record_build(
        self,
        prompt: CompiledPrompt,
        request: PromptBuildRequest,
        build_time_ms: float,
        cache_hit: bool = False,
    ) -> None:
        """Record a prompt build metric."""
        record = PromptMetricRecord(
            prompt_id=prompt.prompt_id,
            review_type=request.review_type.value,
            provider=request.provider,
            model=request.model,
            total_tokens=prompt.total_tokens,
            prompt_size_bytes=len(prompt.system_prompt + prompt.user_prompt),
            compression_ratio=prompt.token_metadata.compression_ratio,
            build_time_ms=build_time_ms,
            cache_hit=cache_hit,
            estimated_cost_usd=prompt.token_metadata.estimated_cost_usd,
            sections_count=len(prompt.sections),
            files_included=prompt.explainability.files_retrieved,
            created_at=time.time(),
            metadata={
                "budget_limit": request.token_budget,
                "repo_size": request.repo_size.value,
                "enable_compression": request.enable_compression,
            },
        )

        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]

    async def get_metrics(self, prompt_id: str) -> Optional[dict]:
        """Get metrics for a specific prompt."""
        for record in reversed(self._records):
            if record.prompt_id == prompt_id:
                return {
                    "prompt_id": record.prompt_id,
                    "review_type": record.review_type,
                    "provider": record.provider,
                    "model": record.model,
                    "total_tokens": record.total_tokens,
                    "prompt_size_bytes": record.prompt_size_bytes,
                    "compression_ratio": record.compression_ratio,
                    "build_time_ms": record.build_time_ms,
                    "cache_hit": record.cache_hit,
                    "estimated_cost_usd": record.estimated_cost_usd,
                    "sections_count": record.sections_count,
                    "files_included": record.files_included,
                    "created_at": record.created_at,
                }
        return None

    async def get_aggregate_metrics(
        self,
        review_type: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> dict:
        """Get aggregate metrics, optionally filtered."""
        filtered = self._records
        if review_type:
            filtered = [r for r in filtered if r.review_type == review_type]
        if provider:
            filtered = [r for r in filtered if r.provider == provider]

        if not filtered:
            return {
                "count": 0,
                "avg_tokens": 0,
                "avg_build_time_ms": 0,
                "avg_compression_ratio": 1.0,
                "cache_hit_rate": 0.0,
                "total_cost_usd": 0.0,
            }

        total_tokens = sum(r.total_tokens for r in filtered)
        total_build_time = sum(r.build_time_ms for r in filtered)
        total_compression = sum(r.compression_ratio for r in filtered)
        cache_hits = sum(1 for r in filtered if r.cache_hit)
        total_cost = sum(r.estimated_cost_usd for r in filtered)

        count = len(filtered)
        return {
            "count": count,
            "avg_tokens": total_tokens // count,
            "avg_build_time_ms": total_build_time / count,
            "avg_compression_ratio": total_compression / count,
            "cache_hit_rate": cache_hits / count,
            "total_cost_usd": total_cost,
        }

    def get_stats(self) -> dict:
        """Get observability stats."""
        return {
            "total_records": len(self._records),
            "max_records": self._max_records,
        }


observability = PromptObservability()
