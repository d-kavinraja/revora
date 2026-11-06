import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.operation import OperationJobRead
from app.services.operation_service import operation_service

router = APIRouter()


@router.get("", response_model=list[OperationJobRead])
async def list_operations(
    active_only: bool = Query(default=False),
    operation_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    jobs = await operation_service.list_for_user(
        db,
        current_user,
        active_only=active_only,
        operation_type=operation_type,
        limit=limit,
    )
    return jobs


@router.get("/{job_id}", response_model=OperationJobRead)
async def get_operation(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await operation_service.get_for_user(db, current_user, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Operation job not found")
    return job
