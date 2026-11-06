import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.queue.operation_models import OperationJob


class OperationService:
    @staticmethod
    def _dedupe_key(operation_type: str, user_id: uuid.UUID, key_id: uuid.UUID | None = None, provider: str | None = None) -> str:
        if operation_type == "api_key_test":
            return f"api_key_test:{key_id}"
        if operation_type == "api_key_validate_all":
            return f"api_key_validate_all:{user_id}"
        if operation_type == "provider_health_check":
            return f"provider_health_check:{user_id}:{provider}"
        return f"{operation_type}:{user_id}"

    async def _find_active(self, db: AsyncSession, dedupe_key: str) -> OperationJob | None:
        stmt = select(OperationJob).where(
            OperationJob.active_dedupe_key == dedupe_key,
            OperationJob.status.in_(["queued", "running"]),
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def enqueue_api_key_test(
        self, db: AsyncSession, user: User, key_id: uuid.UUID
    ) -> tuple[OperationJob, bool]:
        dedupe_key = self._dedupe_key("api_key_test", user.id, key_id=key_id)
        existing = await self._find_active(db, dedupe_key)
        if existing is not None:
            return existing, False

        job = OperationJob(
            user_id=user.id,
            operation_type="api_key_test",
            status="queued",
            payload={"key_id": str(key_id)},
            progress_current=0,
            progress_total=1,
            active_dedupe_key=dedupe_key,
        )
        db.add(job)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = await self._find_active(db, dedupe_key)
            if existing is not None:
                return existing, False
            raise
        await db.refresh(job)
        return job, True

    async def enqueue_validate_all(
        self, db: AsyncSession, user: User
    ) -> tuple[OperationJob, bool]:
        dedupe_key = self._dedupe_key("api_key_validate_all", user.id)
        existing = await self._find_active(db, dedupe_key)
        if existing is not None:
            return existing, False

        from app.models.api_key import ApiKey

        stmt = select(ApiKey.id).where(ApiKey.user_id == user.id)
        result = await db.execute(stmt)
        key_ids = [str(row[0]) for row in result.all()]

        job = OperationJob(
            user_id=user.id,
            operation_type="api_key_validate_all",
            status="queued",
            payload={"key_ids": key_ids},
            progress_current=0,
            progress_total=len(key_ids),
            active_dedupe_key=dedupe_key,
        )
        db.add(job)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = await self._find_active(db, dedupe_key)
            if existing is not None:
                return existing, False
            raise
        await db.refresh(job)
        return job, True

    async def enqueue_provider_health_check(
        self, db: AsyncSession, user: User, provider: str
    ) -> tuple[OperationJob, bool]:
        dedupe_key = self._dedupe_key(
            "provider_health_check", user.id, provider=provider.lower()
        )
        existing = await self._find_active(db, dedupe_key)
        if existing is not None:
            return existing, False

        job = OperationJob(
            user_id=user.id,
            operation_type="provider_health_check",
            status="queued",
            payload={"provider": provider.lower()},
            progress_current=0,
            progress_total=1,
            active_dedupe_key=dedupe_key,
        )
        db.add(job)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = await self._find_active(db, dedupe_key)
            if existing is not None:
                return existing, False
            raise
        await db.refresh(job)
        return job, True

    async def get_for_user(
        self, db: AsyncSession, user: User, job_id: uuid.UUID
    ) -> OperationJob | None:
        stmt = select(OperationJob).where(
            OperationJob.id == job_id, OperationJob.user_id == user.id
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def list_for_user(
        self,
        db: AsyncSession,
        user: User,
        *,
        active_only: bool = False,
        operation_type: str | None = None,
        limit: int = 20,
    ) -> list[OperationJob]:
        stmt = select(OperationJob).where(OperationJob.user_id == user.id)
        if active_only:
            stmt = stmt.where(OperationJob.status.in_(["queued", "running"]))
        if operation_type:
            stmt = stmt.where(OperationJob.operation_type == operation_type)
        stmt = stmt.order_by(OperationJob.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())


operation_service = OperationService()
