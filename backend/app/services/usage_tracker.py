import uuid
import hashlib
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.observability import LLMRequestLog


class UsageTracker:
    async def log_request(
        self,
        db: AsyncSession,
        request_id: str,
        user_id: uuid.UUID,
        provider: str,
        model: str,
        feature: str,
        messages: list,
        status: str,
        latency_ms: float,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        started_at: datetime,
        completed_at: Optional[datetime] = None,
        response_text: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        was_fallback: bool = False,
        original_provider: Optional[str] = None,
        attempt_number: int = 1,
        api_key_id: Optional[uuid.UUID] = None,
        review_id: Optional[uuid.UUID] = None,
    ) -> LLMRequestLog:
        messages_str = str(messages)
        messages_hash = hashlib.sha256(messages_str.encode()).hexdigest()

        response_hash = None
        if response_text:
            response_hash = hashlib.sha256(response_text.encode()).hexdigest()

        log = LLMRequestLog(
            request_id=request_id,
            user_id=user_id,
            provider=provider,
            model=model,
            feature=feature,
            messages_hash=messages_hash,
            status=status,
            response_hash=response_hash,
            error_type=error_type,
            error_message=error_message,
            started_at=started_at,
            completed_at=completed_at or datetime.now(timezone.utc),
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            was_fallback=was_fallback,
            original_provider=original_provider,
            attempt_number=attempt_number,
            api_key_id=api_key_id,
            review_id=review_id,
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        return log

    def _apply_filters(
        self, query,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ):
        if provider:
            query = query.where(LLMRequestLog.provider == provider)
        if model:
            query = query.where(LLMRequestLog.model == model)
        if api_key_id:
            try:
                parsed_api_key_id = uuid.UUID(api_key_id) if isinstance(api_key_id, str) else api_key_id
                query = query.where(LLMRequestLog.api_key_id == parsed_api_key_id)
            except Exception:
                pass
        if repo_id:
            from app.models.review import Review
            from app.models.github import PullRequest
            try:
                parsed_repo_id = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
                query = query.join(Review, Review.id == LLMRequestLog.review_id)
                query = query.join(PullRequest, PullRequest.id == Review.pr_id)
                query = query.where(PullRequest.repo_id == parsed_repo_id)
            except Exception:
                pass
        if start_date:
            query = query.where(LLMRequestLog.created_at >= start_date)
        if end_date:
            query = query.where(LLMRequestLog.created_at <= end_date)
        return query

    async def get_user_requests(
        self, db: AsyncSession, user_id: uuid.UUID,
        limit: int = 50, offset: int = 0,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[LLMRequestLog]:
        query = select(LLMRequestLog).where(LLMRequestLog.user_id == user_id)
        query = self._apply_filters(query, provider, model, api_key_id, repo_id, start_date, end_date)
        query = query.order_by(LLMRequestLog.created_at.desc()).offset(offset).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_error_summary(
        self, db: AsyncSession, user_id: uuid.UUID,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        if not start_date:
            start_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            
        query = select(LLMRequestLog).where(
            LLMRequestLog.user_id == user_id,
            LLMRequestLog.status == "error",
        )
        query = self._apply_filters(query, provider, model, api_key_id, repo_id, start_date, end_date)
        result = await db.execute(query)
        errors = list(result.scalars().all())

        by_type = {}
        by_provider = {}
        for e in errors:
            by_type[e.error_type or "unknown"] = by_type.get(e.error_type or "unknown", 0) + 1
            by_provider[e.provider] = by_provider.get(e.provider, 0) + 1

        total_query = select(func.count(LLMRequestLog.id)).where(LLMRequestLog.user_id == user_id)
        total_query = self._apply_filters(total_query, provider, model, api_key_id, repo_id, start_date, end_date)
        total_result = await db.execute(total_query)
        total = total_result.scalar() or 0

        return {
            "total_errors": len(errors),
            "by_type": by_type,
            "by_provider": by_provider,
            "error_rate": len(errors) / max(total, 1),
        }

    async def get_latency_stats(
        self, db: AsyncSession, user_id: uuid.UUID, 
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        query = select(LLMRequestLog.latency_ms).where(
            LLMRequestLog.user_id == user_id,
            LLMRequestLog.status == "success",
        )
        query = self._apply_filters(query, provider, model, api_key_id, repo_id, start_date, end_date)
        result = await db.execute(query)
        latencies = sorted([r[0] for r in result.all()])

        if not latencies:
            return {"p50": 0, "p90": 0, "p99": 0, "avg": 0, "min": 0, "max": 0}

        n = len(latencies)
        return {
            "p50": latencies[n // 2],
            "p90": latencies[int(n * 0.9)],
            "p99": latencies[int(n * 0.99)],
            "avg": sum(latencies) / n,
            "min": latencies[0],
            "max": latencies[-1],
        }

    async def get_feature_usage(
        self, db: AsyncSession, user_id: uuid.UUID,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Dict]:
        query = select(LLMRequestLog).where(LLMRequestLog.user_id == user_id)
        query = self._apply_filters(query, provider, model, api_key_id, repo_id, start_date, end_date)
        result = await db.execute(query)
        records = list(result.scalars().all())

        features = {}
        for r in records:
            if r.feature not in features:
                features[r.feature] = {"count": 0, "cost": 0.0, "tokens": 0, "latency": 0.0}
            features[r.feature]["count"] += 1
            features[r.feature]["cost"] += r.cost_usd
            features[r.feature]["tokens"] += r.input_tokens + r.output_tokens
            features[r.feature]["latency"] += r.latency_ms

        result_list = []
        for feat, data in features.items():
            result_list.append({
                "feature": feat,
                "request_count": data["count"],
                "total_cost_usd": round(data["cost"], 6),
                "total_tokens": data["tokens"],
                "avg_latency_ms": round(data["latency"] / data["count"], 2) if data["count"] else 0,
            })
        return result_list

    async def get_provider_comparison(
        self, db: AsyncSession, user_id: uuid.UUID,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Dict]:
        query = select(LLMRequestLog).where(LLMRequestLog.user_id == user_id)
        query = self._apply_filters(query, provider, model, api_key_id, repo_id, start_date, end_date)
        result = await db.execute(query)
        records = list(result.scalars().all())

        providers = {}
        for r in records:
            if r.provider not in providers:
                providers[r.provider] = {"count": 0, "success": 0, "cost": 0.0, "tokens": 0, "latency": 0.0}
            providers[r.provider]["count"] += 1
            if r.status == "success":
                providers[r.provider]["success"] += 1
            providers[r.provider]["cost"] += r.cost_usd
            providers[r.provider]["tokens"] += r.input_tokens + r.output_tokens
            providers[r.provider]["latency"] += r.latency_ms

        result_list = []
        for prov, data in providers.items():
            result_list.append({
                "provider": prov,
                "request_count": data["count"],
                "success_rate": data["success"] / max(data["count"], 1),
                "avg_latency_ms": round(data["latency"] / data["count"], 2) if data["count"] else 0,
                "total_cost_usd": round(data["cost"], 6),
                "total_tokens": data["tokens"],
            })
        return result_list

usage_tracker = UsageTracker()
