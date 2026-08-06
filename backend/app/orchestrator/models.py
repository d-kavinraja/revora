import time
from dataclasses import dataclass, field
from datetime import datetime

# ── Execution Modes ──────────────────────────────────────────────
# These string constants define how an execution context was resolved.
CONFIG_SOURCE_REPO = "repo_config"      # MODE 1: repo has explicit provider/model/key
CONFIG_SOURCE_ROUTING = "user_routing"   # MODE 2: user routing preferences
CONFIG_SOURCE_NONE = "none"              # MODE 3: nothing configured


@dataclass
class ExecutionContext:
    """Immutable execution context for a single review.
    
    Once resolved, this context is fixed for the entire review lifetime.
    Revora MUST NOT switch providers, models, or API keys during execution.
    """
    provider: str
    model: str
    api_key_id: str | None = None
    source: str = CONFIG_SOURCE_REPO      # How this context was resolved
    resolved_at: float = field(default_factory=time.time)

    @property
    def is_explicit(self) -> bool:
        """True when the repository has an explicit provider/model/key mapping."""
        return self.source == CONFIG_SOURCE_REPO

    @property
    def is_routed(self) -> bool:
        """True when the provider was selected via user routing preferences."""
        return self.source == CONFIG_SOURCE_ROUTING


@dataclass
class ProviderConfig:
    """Lightweight provider descriptor — no longer carries fallback state."""
    name: str
    model: str
    priority: int = 0
    timeout_seconds: int = 300


@dataclass
class UsageStats:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0
    timestamp: datetime | None = None


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
