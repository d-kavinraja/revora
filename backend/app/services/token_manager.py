import uuid
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.models.token_usage import LlmTokenUsage


class TokenManager:
    async def record_usage(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        input_cost_usd: float,
        output_cost_usd: float,
        feature: str,
        latency_ms: float,
        api_key_id: Optional[uuid.UUID] = None,
        review_id: Optional[uuid.UUID] = None,
        request_id: Optional[str] = None,
        is_fallback: bool = False,
        cached: bool = False,
    ) -> LlmTokenUsage:
        record = LlmTokenUsage(
            user_id=user_id,
            provider=provider,
            model=model,
            api_key_id=api_key_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            input_cost_usd=input_cost_usd,
            output_cost_usd=output_cost_usd,
            total_cost_usd=input_cost_usd + output_cost_usd,
            feature=feature,
            review_id=review_id,
            request_id=request_id,
            latency_ms=latency_ms,
            is_fallback=is_fallback,
            cached=cached,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record

    def _apply_filters(self, query, provider: Optional[str] = None, model: Optional[str] = None, api_key_id: Optional[str] = None, repo_id: Optional[str] = None):
        if provider:
            query = query.where(LlmTokenUsage.provider == provider)
        if model:
            query = query.where(LlmTokenUsage.model == model)
        if api_key_id:
            import uuid
            try:
                parsed_api_key_id = uuid.UUID(api_key_id) if isinstance(api_key_id, str) else api_key_id
                query = query.where(LlmTokenUsage.api_key_id == parsed_api_key_id)
            except Exception:
                pass
        if repo_id:
            from app.models.review import Review
            from app.models.github import PullRequest
            import uuid
            try:
                parsed_repo_id = uuid.UUID(repo_id) if isinstance(repo_id, str) else repo_id
                query = query.join(Review, Review.id == LlmTokenUsage.review_id)
                query = query.join(PullRequest, PullRequest.id == Review.pr_id)
                query = query.where(PullRequest.repo_id == parsed_repo_id)
            except Exception:
                pass
        return query

    async def get_usage_by_user(
        self, db: AsyncSession, user_id: uuid.UUID,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
        provider: Optional[str] = None, model: Optional[str] = None,
        api_key_id: Optional[str] = None, repo_id: Optional[str] = None,
        limit: int = 100, offset: int = 0,
    ) -> List[LlmTokenUsage]:
        query = select(LlmTokenUsage).where(LlmTokenUsage.user_id == user_id)
        if start:
            query = query.where(LlmTokenUsage.created_at >= start)
        if end:
            query = query.where(LlmTokenUsage.created_at <= end)
        
        query = self._apply_filters(query, provider, model, api_key_id, repo_id)
        
        query = query.order_by(LlmTokenUsage.created_at.desc()).offset(offset).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_cost_breakdown(
        self, db: AsyncSession, user_id: uuid.UUID,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
        provider: Optional[str] = None, model: Optional[str] = None,
        api_key_id: Optional[str] = None, repo_id: Optional[str] = None,
    ) -> Dict:
        query = select(LlmTokenUsage).where(LlmTokenUsage.user_id == user_id)
        if start:
            query = query.where(LlmTokenUsage.created_at >= start)
        if end:
            query = query.where(LlmTokenUsage.created_at <= end)
            
        query = self._apply_filters(query, provider, model, api_key_id, repo_id)
        
        result = await db.execute(query)
        records = list(result.scalars().all())

        by_provider = {}
        by_model = {}
        by_feature = {}
        total_cost = 0.0
        total_tokens = 0

        for r in records:
            total_cost += r.total_cost_usd
            total_tokens += r.total_tokens

            by_provider[r.provider] = by_provider.get(r.provider, 0) + r.total_cost_usd
            by_model[r.model] = by_model.get(r.model, 0) + r.total_cost_usd
            by_feature[r.feature] = by_feature.get(r.feature, 0) + r.total_cost_usd

        return {
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
            "by_provider": by_provider,
            "by_model": by_model,
            "by_feature": by_feature,
        }

    async def get_total_cost(
        self, db: AsyncSession, user_id: uuid.UUID,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
        provider: Optional[str] = None, model: Optional[str] = None,
        api_key_id: Optional[str] = None, repo_id: Optional[str] = None,
    ) -> float:
        breakdown = await self.get_cost_breakdown(
            db, user_id, start, end, provider, model, api_key_id, repo_id
        )
        return breakdown["total_cost_usd"]

    async def get_daily_trend(
        self, db: AsyncSession, user_id: uuid.UUID,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
        provider: Optional[str] = None, model: Optional[str] = None,
        api_key_id: Optional[str] = None, repo_id: Optional[str] = None,
    ) -> List[Dict]:
        query = select(
            func.date_trunc('day', LlmTokenUsage.created_at).label('day'),
            func.sum(LlmTokenUsage.total_cost_usd).label('cost_usd'),
            func.sum(LlmTokenUsage.total_tokens).label('tokens')
        ).where(LlmTokenUsage.user_id == user_id)
        
        if start:
            query = query.where(LlmTokenUsage.created_at >= start)
        if end:
            query = query.where(LlmTokenUsage.created_at <= end)
            
        query = self._apply_filters(query, provider, model, api_key_id, repo_id)
        
        query = query.group_by('day').order_by('day')
        
        result = await db.execute(query)
        rows = result.all()
        
        return [
            {
                "date": row.day.strftime("%Y-%m-%d") if row.day else "",
                "cost_usd": float(row.cost_usd) if row.cost_usd else 0.0,
                "tokens": int(row.tokens) if row.tokens else 0
            }
            for row in rows
        ]

token_manager = TokenManager()
