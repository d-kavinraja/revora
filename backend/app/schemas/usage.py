import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyHealthRead(BaseModel):
    id: uuid.UUID
    key_id: uuid.UUID
    status: str
    error_type: str | None = None
    error_message: str | None = None
    latency_ms: float | None = None
    checked_at: datetime
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiKeyRotate(BaseModel):
    api_key: str = Field(..., description="The new raw API key")


class PerKeyValidationResult(BaseModel):
    status: str = Field(
        ...,
        description="Per-credential outcome: success | failed | busy",
        pattern="^(success|failed|busy)$",
    )
    message: str = Field(..., description="Frontend-safe summary message")
    error_type: str | None = Field(
        default=None,
        description="Machine-readable failure category for UI/observability",
    )


class BulkValidationSummary(BaseModel):
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    busy: int = 0


class BulkValidateResult(BaseModel):
    results: dict[str, PerKeyValidationResult]  # key_id -> per-key outcome
    summary: BulkValidationSummary = BulkValidationSummary()


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
    provider: str | None = None
    feature: str | None = None


class CostBudgetUpdate(BaseModel):
    limit_usd: float | None = Field(None, gt=0)
    is_active: bool | None = None


class CostBudgetRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    budget_type: str
    limit_usd: float
    spent_usd: float
    provider: str | None = None
    feature: str | None = None
    is_active: bool
    reset_at: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
