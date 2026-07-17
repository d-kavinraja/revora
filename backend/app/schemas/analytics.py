import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class LLMRequestLogRead(BaseModel):
    id: uuid.UUID
    request_id: str
    user_id: uuid.UUID
    provider: str
    model: str
    feature: str
    status: str
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    was_fallback: bool
    original_provider: Optional[str] = None
    attempt_number: int
    created_at: datetime

    model_config = {"from_attributes": True}


class LatencyStats(BaseModel):
    p50: float
    p90: float
    p99: float
    avg: float
    min: float
    max: float


class ErrorSummary(BaseModel):
    total_errors: int
    by_type: dict  # error_type -> count
    by_provider: dict  # provider -> count
    error_rate: float


class FeatureUsage(BaseModel):
    feature: str
    request_count: int
    total_cost_usd: float
    total_tokens: int
    avg_latency_ms: float


class ProviderComparison(BaseModel):
    provider: str
    request_count: int
    success_rate: float
    avg_latency_ms: float
    total_cost_usd: float
    total_tokens: int
