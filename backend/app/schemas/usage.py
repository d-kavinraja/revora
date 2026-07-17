import uuid
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class ApiKeyHealthRead(BaseModel):
    id: uuid.UUID
    key_id: uuid.UUID
    status: str
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: Optional[float] = None
    checked_at: datetime
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApiKeyRotate(BaseModel):
    api_key: str = Field(..., description="The new raw API key")


class BulkValidateResult(BaseModel):
    results: dict  # key_id -> {"status": "success"|"failed", "message": str}


class UsageSummary(BaseModel):
    period: str  # "today", "week", "month"
    total_cost_usd: float
    total_tokens: int
    input_tokens: int
    output_tokens: int
    request_count: int
    by_provider: dict  # provider -> cost
    by_model: dict  # model -> cost
    by_feature: dict  # feature -> cost


class DailyCost(BaseModel):
    date: str
    cost_usd: float
    tokens: int


class UsageRecordRead(BaseModel):
    id: uuid.UUID
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost_usd: float
    feature: str
    latency_ms: float
    is_fallback: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CostBudgetCreate(BaseModel):
    budget_type: str = Field(..., pattern="^(daily|monthly)$")
    limit_usd: float = Field(..., gt=0)
    provider: Optional[str] = None
    feature: Optional[str] = None


class CostBudgetUpdate(BaseModel):
    limit_usd: Optional[float] = Field(None, gt=0)
    is_active: Optional[bool] = None


class CostBudgetRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    budget_type: str
    limit_usd: float
    spent_usd: float
    provider: Optional[str] = None
    feature: Optional[str] = None
    is_active: bool
    reset_at: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
