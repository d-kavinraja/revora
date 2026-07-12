from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class ProviderConfig:
    name: str
    model: str
    priority: int = 0
    max_retries: int = 3
    timeout_seconds: int = 60
    is_available: bool = True
    last_health_check: Optional[datetime] = None
    success_rate: float = 1.0
    avg_latency_ms: float = 0.0


@dataclass
class UsageStats:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0
    timestamp: Optional[datetime] = None


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    estimated_cost_usd: float = 0.0
    is_fallback: bool = False
