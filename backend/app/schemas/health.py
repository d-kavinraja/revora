import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ProviderHealthRead(BaseModel):
    id: uuid.UUID
    provider: str
    status: str
    avg_latency_ms: float
    success_rate: float
    error_rate: float
    total_requests: int
    failed_requests: int
    circuit_state: str
    circuit_opened_at: datetime | None = None
    consecutive_failures: int
    last_error: str | None = None
    last_error_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class FailoverLogRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    feature: str
    failed_provider: str
    failed_model: str
    failure_reason: str
    fallback_provider: str
    fallback_model: str
    attempt_number: int
    total_latency_ms: float
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthDashboard(BaseModel):
    providers: list[ProviderHealthRead]
    recent_failovers: list[FailoverLogRead]
    circuit_breakers: dict


class ModelRoute(BaseModel):
    provider: str
    model: str
    litellm_model: str
    api_key_id: str | None = None
    estimated_cost_per_1k: float = 0.0
    available_models: list[dict[str, Any]] = []


class RoutingPreferences(BaseModel):
    routing: dict
