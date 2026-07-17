# Revora BYOK LLM Orchestrator — Phased Implementation Plan

## Executive Summary

This plan transforms Revora's hardcoded 5-provider priority fallback into a production-grade BYOK (Bring Your Own Key) LLM Orchestrator supporting 10 providers, per-feature routing, DB-backed token/cost tracking, health monitoring, retry/failover, usage analytics, and a full observability stack.

**Current State**: In-memory orchestrator, 6 hardcoded providers, basic API key CRUD, no usage persistence.

**Target State**: Provider Registry with 10 providers, Enhanced API Key Manager with rotation/health, per-feature Model Router, DB-backed Token Manager & Cost Estimator, Health Monitor with circuit breakers, Retry/Failover (user-owned keys only), Usage Tracker, Observability (OpenTelemetry), and a comprehensive frontend dashboard.

---

## Existing Architecture Summary

### Backend Stack
- **Framework**: Python/FastAPI
- **ORM**: SQLAlchemy 2 async
- **Database**: PostgreSQL with JSONB
- **LLM**: LiteLLM integration
- **Encryption**: Fernet (AES-256)
- **Migrations**: Alembic

### Frontend Stack
- **Framework**: Next.js 16
- **UI**: shadcn/ui + Tailwind
- **State**: Zustand (useAuthStore)
- **HTTP**: Axios with interceptors

### Existing Tables (22)
| Table | Purpose |
|-------|---------|
| users | User accounts |
| api_keys | Encrypted LLM provider keys |
| organizations | Multi-tenant orgs |
| org_members | Org membership |
| teams | Team grouping |
| team_members | Team membership |
| installations | GitHub App installs |
| repositories | Connected repos |
| pull_requests | PR tracking |
| reviews | Review orchestration |
| review_comments | Review findings |
| repository_knowledge | Repo knowledge base |
| repository_rules | Repo-specific rules |
| repository_indexes | Code indexes |
| repository_intelligence | Repo intelligence |
| review_events | Review lifecycle events |
| review_metrics | Review performance metrics |
| prompt_templates | Prompt definitions |
| prompt_versions | Prompt A/B versions |
| prompt_cache | Prompt caching |
| prompt_metrics | Prompt build metrics |
| token_usage | Token consumption tracking |

### Current Orchestrator
- **File**: `app/orchestrator/orchestrator.py`
- **Providers**: 5 hardcoded (gemini, openai, anthropic, deepseek, groq)
- **Strategy**: Priority-based fallback with in-memory state
- **Cost**: Hardcoded COST_TABLE per provider
- **Usage**: In-memory list (lost on restart)

### Current API Keys
- **File**: `app/models/api_key.py`
- **Fields**: user_id, provider, encrypted_key, label, is_valid, last_used_at
- **Service**: `app/services/api_key_service.py`
- **Providers**: 6 (openai, anthropic, gemini, groq, deepseek, grok)

---

## Phase 1: Provider Registry & Enhanced API Key Manager

**Goal**: Establish the foundation — DB-backed provider registry and enhanced key lifecycle management.

**Duration**: ~3-4 days

### 1.1 New Database Tables

#### `provider_registry` — Provider configuration store
```python
# app/models/provider.py

class ProviderRegistry(Base):
    """DB-backed provider registry replacing hardcoded PROVIDER_PRIORITY."""
    __tablename__ = "provider_registry"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # "openai"
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)      # "OpenAI"
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # "openai"
    
    # LiteLLM mapping
    litellm_provider: Mapped[str] = mapped_column(String(50), nullable=False)   # "openai"
    api_key_prefix: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # "sk-"
    api_key_min_length: Mapped[int] = mapped_column(Integer, default=15)
    
    # Configuration
    base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    default_model: Mapped[str] = mapped_column(String(100), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    
    # Features
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_function_calling: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_reasoning: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Status
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
```

#### `api_key_health` — Key health tracking
```python
# app/models/api_key.py (extend existing)

class ApiKeyHealth(Base):
    """Health history for API keys."""
    __tablename__ = "api_key_health"

    key_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("api_keys.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "healthy", "degraded", "unhealthy"
    error_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # "rate_limit", "auth_error", "timeout"
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

### 1.2 Alembic Migration

**File**: `backend/alembic/versions/20260716_1100_provider_registry.py`

```python
def upgrade():
    op.create_table('provider_registry', ...)
    op.create_table('api_key_health', ...)
    op.create_index('ix_api_key_health_key_id', 'api_key_health', ['key_id'])
    
    # Seed 10 providers
    op.execute("""
        INSERT INTO provider_registry (name, display_name, slug, litellm_provider, default_model, priority, ...)
        VALUES 
            ('openai', 'OpenAI', 'openai', 'openai', 'gpt-4o', 1, ...),
            ('anthropic', 'Anthropic', 'anthropic', 'anthropic', 'claude-sonnet-4-20250514', 2, ...),
            ('gemini', 'Google Gemini', 'gemini', 'gemini', 'gemini-2.5-flash', 0, ...),
            ('deepseek', 'DeepSeek', 'deepseek', 'deepseek', 'deepseek-chat', 3, ...),
            ('groq', 'Groq', 'groq', 'groq', 'llama-3.3-70b-versatile', 4, ...),
            ('grok', 'xAI Grok', 'grok', 'xai', 'grok-2', 5, ...),
            ('mistral', 'Mistral AI', 'mistral', 'mistral', 'mistral-large-latest', 6, ...),
            ('cohere', 'Cohere', 'cohere', 'cohere', 'command-r-plus', 7, ...),
            ('bedrock', 'AWS Bedrock', 'bedrock', 'bedrock', 'anthropic.claude-3-5-sonnet', 8, ...),
            ('openrouter', 'OpenRouter', 'openrouter', 'openrouter', 'anthropic/claude-3.5-sonnet', 9, ...);
    """)
```

### 1.3 Backend Files

#### `app/services/provider_registry.py` — Provider CRUD + discovery
```python
class ProviderRegistryService:
    async def get_all(db) -> List[ProviderRegistry]
    async def get_by_slug(db, slug) -> ProviderRegistry
    async def get_enabled(db) -> List[ProviderRegistry]
    async def update(db, slug, data) -> ProviderRegistry
    async def toggle(db, slug, enabled) -> ProviderRegistry
```

#### `app/services/api_key_manager.py` — Enhanced key management
```python
class ApiKeyManager:
    # Existing (enhanced)
    async def create(db, user_id, data) -> ApiKey  # + health check on create
    async def update(db, key_id, data) -> ApiKey
    async def delete(db, key_id) -> None
    async def get_decrypted(db, user_id, provider) -> str
    
    # New
    async def rotate(db, key_id, new_key) -> ApiKey  # Atomic rotation
    async def bulk_validate(db, user_id) -> Dict  # Validate all keys
    async def record_health(db, key_id, status, error) -> None  # Health log
    async def get_health_history(db, key_id, limit) -> List[ApiKeyHealth]
    async def get_usable_key(db, user_id, provider) -> Optional[ApiKey]  # Best key for provider
```

#### `app/schemas/provider.py` — Pydantic models
```python
class ProviderRegistryRead(BaseModel): ...
class ProviderRegistryUpdate(BaseModel): ...
class ApiKeyHealthRead(BaseModel): ...
```

### 1.4 API Endpoints

**File**: `backend/app/api/v1/endpoints/providers.py`

```
GET    /api/v1/providers              — List all providers (admin sees disabled too)
GET    /api/v1/providers/{slug}       — Get provider details
PUT    /api/v1/providers/{slug}       — Update provider config (admin)
POST   /api/v1/providers/{slug}/toggle — Enable/disable provider (admin)
GET    /api/v1/providers/capabilities — Capabilities matrix
```

**File**: `backend/app/api/v1/endpoints/api_keys.py` (extend)

```
POST   /api/v1/api-keys/{id}/rotate   — Rotate key (atomic)
POST   /api/v1/api-keys/validate-all  — Bulk validate all user keys
GET    /api/v1/api-keys/{id}/health   — Get health history
```

### 1.5 Router Registration

**File**: `backend/app/api/v1/router.py` (update)
```python
from app.api.v1.endpoints import providers
api_router.include_router(providers.router, prefix="/providers", tags=["providers"])
```

### 1.6 Frontend Files

#### `frontend/src/lib/api.ts` (extend)
```typescript
// New types
export interface Provider { ... }
export interface ApiKeyHealth { ... }

// New API methods
export const api = {
  // ... existing
  getProviders: () => apiClient.get<Provider[]>('/providers').then(r => r.data),
  getProviderCapabilities: () => apiClient.get<Record<string, string[]>>('/providers/capabilities').then(r => r.data),
  rotateApiKey: (id: string, newKey: string) => apiClient.post<ApiKey>(`/api-keys/${id}/rotate`, { api_key: newKey }).then(r => r.data),
  getKeyHealth: (id: string) => apiClient.get<ApiKeyHealth[]>(`/api-keys/${id}/health`).then(r => r.data),
  validateAllKeys: () => apiClient.post<{results: Record<string, string>}>('/api-keys/validate-all').then(r => r.data),
};
```

#### `frontend/src/app/(dashboard)/settings/providers/page.tsx` — Provider management page
- Provider grid with enable/disable toggles
- Capability badges (streaming, vision, function calling)
- Default model display
- Priority drag-reorder (admin)

#### `frontend/src/app/(dashboard)/settings/api-keys/page.tsx` (enhance)
- Add rotation button per key
- Health status indicators (healthy/degraded/unhealthy)
- Health history timeline
- Bulk "Validate All" button

### 1.7 Tests

**File**: `backend/tests/services/test_provider_registry.py`
```python
async def test_get_all_providers(db): ...
async def test_seed_providers_on_migration(db): ...
async def test_toggle_provider(db): ...
async def test_provider_capabilities_matrix(db): ...
```

**File**: `backend/tests/services/test_api_key_manager.py`
```python
async def test_create_key_triggers_health_check(db): ...
async def test_rotate_key_atomic(db): ...
async def test_bulk_validate(db): ...
async def test_health_recording(db): ...
async def test_get_usable_key_fallback(db): ...
```

---

## Phase 2: Token Manager & Cost Estimator (DB-backed)

**Goal**: Persist all token usage and cost data to DB, replacing in-memory tracking.

**Duration**: ~2-3 days

### 2.1 New Database Tables

#### `token_usage_records` — Granular per-request token tracking
```python
# app/models/token_usage.py

class TokenUsageRecord(Base):
    """Per-request token consumption — the source of truth."""
    __tablename__ = "token_usage_records"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("api_keys.id"), nullable=True)
    
    # Token counts
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Cost (computed at write time from cost table)
    input_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    output_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Context
    feature: Mapped[str] = mapped_column(String(50), nullable=False)  # "code_review", "summarization", etc.
    review_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("reviews.id"), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Idempotency
    
    # Metadata
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
```

#### `cost_budgets` — User/org cost limits
```python
class CostBudget(Base):
    """Budget constraints for cost control."""
    __tablename__ = "cost_budgets"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    
    # Budget
    budget_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "daily", "monthly", "total"
    limit_usd: Mapped[float] = mapped_column(Float, nullable=False)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Scope
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # NULL = all providers
    feature: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)   # NULL = all features
    
    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

### 2.2 Alembic Migration

**File**: `backend/alembic/versions/20260716_1200_token_usage_cost.py`

```python
def upgrade():
    op.create_table('token_usage_records', ...)
    op.create_table('cost_budgets', ...)
    op.create_index('ix_token_usage_user_date', 'token_usage_records', ['user_id', 'created_at'])
    op.create_index('ix_token_usage_provider', 'token_usage_records', ['provider'])
```

### 2.3 Backend Files

#### `app/services/token_manager.py` — Token persistence
```python
class TokenManager:
    async def record_usage(db, data: TokenUsageCreate) -> TokenUsageRecord
    async def get_usage_by_user(db, user_id, start, end) -> List[TokenUsageRecord]
    async def get_usage_by_provider(db, user_id, provider, start, end) -> List[TokenUsageRecord]
    async def get_usage_by_feature(db, user_id, feature, start, end) -> List[TokenUsageRecord]
    async def get_total_cost(db, user_id, start, end) -> float
    async def get_cost_breakdown(db, user_id, start, end) -> Dict  # by provider, model, feature
```

#### `app/services/cost_estimator.py` — Cost calculation + budget enforcement
```python
class CostEstimator:
    # Dynamic cost table (DB-backed, with litellm fallback)
    async def get_rates(db, provider, model) -> CostRates
    async def estimate(db, provider, model, input_tokens, output_tokens) -> float
    
    # Budget
    async def check_budget(db, user_id, provider, feature) -> bool  # Under budget?
    async def get_budgets(db, user_id) -> List[CostBudget]
    async def create_budget(db, user_id, data) -> CostBudget
    async def update_budget(db, budget_id, data) -> CostBudget
    async def reset_periodic_budgets(db) -> int  # Cron job
    
    # Aggregation
    async def get_cost_summary(db, user_id, period) -> CostSummary
    async def get_cost_trend(db, user_id, days) -> List[DailyCost]
```

### 2.4 API Endpoints

**File**: `backend/app/api/v1/endpoints/usage.py`

```
GET    /api/v1/usage/summary          — Cost summary (today/week/month)
GET    /api/v1/usage/trend            — Cost trend over time
GET    /api/v1/usage/breakdown        — Breakdown by provider/model/feature
GET    /api/v1/usage/records          — Paginated usage records

GET    /api/v1/usage/budgets          — List budgets
POST   /api/v1/usage/budgets          — Create budget
PUT    /api/v1/usage/budgets/{id}     — Update budget
DELETE /api/v1/usage/budgets/{id}     — Delete budget
```

### 2.5 Frontend Files

#### `frontend/src/lib/api.ts` (extend)
```typescript
export interface UsageSummary { ... }
export interface CostTrend { ... }
export interface CostBudget { ... }

export const api = {
  // ... existing
  getUsageSummary: (period: string) => apiClient.get<UsageSummary>(`/usage/summary?period=${period}`).then(r => r.data),
  getUsageTrend: (days: number) => apiClient.get<CostTrend[]>(`/usage/trend?days=${days}`).then(r => r.data),
  getUsageBreakdown: (period: string) => apiClient.get<UsageBreakdown>(`/usage/breakdown?period=${period}`).then(r => r.data),
  getBudgets: () => apiClient.get<CostBudget[]>('/usage/budgets').then(r => r.data),
  createBudget: (data: BudgetCreate) => apiClient.post<CostBudget>('/usage/budgets', data).then(r => r.data),
};
```

#### `frontend/src/app/(dashboard)/settings/usage/page.tsx` — Usage dashboard
- Cost summary cards (today/week/month)
- Cost trend chart (recharts)
- Breakdown by provider (pie chart)
- Breakdown by model (bar chart)
- Usage records table with pagination

#### `frontend/src/app/(dashboard)/settings/budgets/page.tsx` — Budget management
- Budget list with progress bars
- Create/edit budget modal
- Budget alert thresholds

### 2.6 Tests

**File**: `backend/tests/services/test_token_manager.py`
```python
async def test_record_usage(db): ...
async def test_usage_aggregation(db): ...
async def test_cost_breakdown(db): ...
```

**File**: `backend/tests/services/test_cost_estimator.py`
```python
async def test_estimate_cost(db): ...
async def test_budget_enforcement(db): ...
async def test_budget_reset(db): ...
```

---

## Phase 3: Health Monitor & Retry/Failover

**Goal**: Circuit-breaker health monitoring and intelligent retry/failover for user-owned keys.

**Duration**: ~3-4 days

### 3.1 New Database Tables

#### `provider_health` — Provider-level health snapshots
```python
# app/models/health.py

class ProviderHealth(Base):
    """Provider health snapshots (periodic + on-demand)."""
    __tablename__ = "provider_health"

    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "healthy", "degraded", "down"
    
    # Metrics
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    success_rate: Mapped[float] = mapped_column(Float, default=1.0)
    error_rate: Mapped[float] = mapped_column(Float, default=0.0)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    failed_requests: Mapped[int] = mapped_column(Integer, default=0)
    
    # Circuit breaker
    circuit_state: Mapped[str] = mapped_column(String(20), default="closed")  # "closed", "open", "half_open"
    circuit_opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    
    # Errors
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

#### `failover_log` — Failover event tracking
```python
class FailoverLog(Base):
    """Tracks every failover event for observability."""
    __tablename__ = "failover_log"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # From
    failed_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    failed_model: Mapped[str] = mapped_column(String(100), nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False)
    
    # To
    fallback_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    fallback_model: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Context
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    total_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
```

### 3.2 Alembic Migration

**File**: `backend/alembic/versions/20260716_1300_health_failover.py`

### 3.3 Backend Files

#### `app/services/health_monitor.py` — Circuit breaker + health tracking
```python
class HealthMonitor:
    # Circuit breaker states
    CLOSED = "closed"     # Normal operation
    OPEN = "circuit_open" # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery

    async def record_success(db, provider, latency_ms) -> None
    async def record_failure(db, provider, error_type, error_msg) -> None
    async def get_circuit_state(db, provider) -> str
    async def should_allow_request(db, provider) -> bool
    async def check_provider(db, provider) -> ProviderHealth  # On-demand health check
    async def check_all_providers(db) -> Dict[str, ProviderHealth]
    async def get_health_dashboard(db) -> HealthDashboard
```

#### `app/services/retry_failover.py` — Intelligent retry with failover
```python
class RetryFailoverService:
    async def execute_with_fallback(
        self,
        db,
        user_id: uuid.UUID,
        feature: str,           # "code_review", "summarization", etc.
        messages: list,
        preferred_provider: Optional[str] = None,
        preferred_model: Optional[str] = None,
        api_key_id: Optional[str] = None,
        max_retries: int = 3,
    ) -> LLMResponse:
        """
        Execute LLM request with retry + failover.
        
        Strategy:
        1. Try preferred provider/model (user's own key)
        2. On failure: try next available provider with user's key
        3. On failure: try system fallback (env keys) — ONLY if user has no keys
        4. Record all attempts to failover_log
        5. Update provider_health + api_key_health
        """
        ...
```

### 3.4 Provider/Model Router (Per-Feature)

#### `app/services/model_router.py` — Feature-aware routing
```python
class ModelRouter:
    """
    Routes LLM requests based on feature requirements.
    Different features may need different model capabilities.
    """
    
    # Feature → capability requirements
    FEATURE_REQUIREMENTS = {
        "code_review": {"min_context_window": 8000, "supports_streaming": True},
        "summarization": {"min_context_window": 4000},
        "security_scan": {"supports_function_calling": True},
        "documentation": {"min_context_window": 16000},
    }

    async def route(
        self,
        db,
        user_id: uuid.UUID,
        feature: str,
        preferred_provider: Optional[str] = None,
        preferred_model: Optional[str] = None,
    ) -> ModelRoute:
        """
        Determine optimal provider + model for the given feature.
        
        Returns ModelRoute with:
        - provider: str
        - model: str
        - api_key_id: Optional[str]
        - litellm_model: str
        - estimated_cost: float
        """
        ...
    
    async def get_available_routes(
        self,
        db,
        user_id: uuid.UUID,
        feature: str,
    ) -> List[ModelRoute]:
        """All viable routes for a feature, ranked by cost/quality."""
        ...
```

### 3.5 API Endpoints

**File**: `backend/app/api/v1/endpoints/health.py`

```
GET    /api/v1/health/providers       — All provider health statuses
GET    /api/v1/health/providers/{slug} — Specific provider health
POST   /api/v1/health/providers/{slug}/check  — On-demand health check
GET    /api/v1/health/failovers       — Recent failover events
GET    /api/v1/health/circuit-breakers — Circuit breaker states
```

**File**: `backend/app/api/v1/endpoints/routing.py`

```
GET    /api/v1/routing/routes         — Available routes for user
GET    /api/v1/routing/recommend/{feature} — Recommended route for feature
```

### 3.6 Orchestrator Refactor

**File**: `app/orchestrator/orestrator.py` (major refactor)

```python
class LLMOrchestrator:
    """
    Refactored orchestrator using:
    - ProviderRegistry (DB) instead of hardcoded PROVIDER_PRIORITY
    - ModelRouter for feature-aware routing
    - RetryFailoverService for intelligent fallback
    - HealthMonitor for circuit breaker
    - TokenManager for DB persistence
    - CostEstimator for budget checks
    """
    
    def __init__(self):
        self.health_monitor = HealthMonitor()
        self.model_router = ModelRouter()
        self.retry_failover = RetryFailoverService()
        self.token_manager = TokenManager()
        self.cost_estimator = CostEstimator()
    
    async def complete(
        self,
        prompt: CompiledPrompt,
        user_id: str,
        feature: str = "code_review",
        preferred_provider: Optional[str] = None,
        preferred_model: Optional[str] = None,
        callback=None,
    ) -> LLMResponse:
        """
        Full pipeline:
        1. ModelRouter selects route
        2. CostEstimator checks budget
        3. HealthMonitor checks circuit breaker
        4. RetryFailoverService executes with fallback
        5. TokenManager records usage
        6. Return response
        """
        ...
```

### 3.7 Frontend Files

#### `frontend/src/app/(dashboard)/settings/health/page.tsx` — Health dashboard
- Provider status cards (green/yellow/red)
- Circuit breaker state indicators
- Health history charts
- On-demand health check buttons
- Recent failover events table

### 3.8 Tests

**File**: `backend/tests/services/test_health_monitor.py`
```python
async def test_circuit_breaker_opens_after_failures(db): ...
async def test_circuit_breaker_half_open_recovery(db): ...
async def test_health_recording(db): ...
```

**File**: `backend/tests/services/test_retry_failover.py`
```python
async def test_fallback_to_next_provider(db): ...
async def test_system_fallback_only_when_no_user_keys(db): ...
async def test_failover_logged(db): ...
```

**File**: `backend/tests/services/test_model_router.py`
```python
async def test_routes_to_capable_provider(db): ...
async def test_feature_requirements_filter(db): ...
async def test_cost_optimization(db): ...
```

---

## Phase 4: Usage Tracker & Observability

**Goal**: Full request tracing, structured logging, and OpenTelemetry integration.

**Duration**: ~2-3 days

### 4.1 New Database Tables

#### `llm_request_log` — Full request/response trace
```python
# app/models/observability.py

class LLMRequestLog(Base):
    """Complete LLM request trace for debugging and analytics."""
    __tablename__ = "llm_request_log"

    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    
    # Request
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    messages_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # Content fingerprint
    
    # Response
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "success", "error", "fallback"
    response_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timing
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    time_to_first_token_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Tokens
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Routing
    was_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    original_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("api_keys.id"), nullable=True)
```

### 4.2 Alembic Migration

**File**: `backend/alembic/versions/20260716_1400_observability.py`

### 4.3 Backend Files

#### `app/services/usage_tracker.py` — Request logging + analytics
```python
class UsageTracker:
    async def log_request(db, data: LLMRequestCreate) -> LLMRequestLog
    async def get_request(db, request_id) -> LLMRequestLog
    async def get_user_requests(db, user_id, limit, offset) -> List[LLMRequestLog]
    async def get_error_rate(db, provider, hours) -> float
    async def get_latency_percentiles(db, provider, hours) -> LatencyStats
    async def get_feature_usage(db, user_id, feature, hours) -> FeatureUsageStats
```

#### `app/middleware/observability.py` — Request tracing middleware
```python
class ObservabilityMiddleware:
    """
    FastAPI middleware for:
    - Request ID propagation
    - Structured logging
    - OpenTelemetry spans
    - Latency tracking
    """
    async def __call__(self, scope, receive, send): ...
```

#### `app/core/tracing.py` — OpenTelemetry setup
```python
def setup_tracing():
    """Configure OpenTelemetry with OTLP exporter."""
    # Traces → Jaeger/Zipkin
    # Metrics → Prometheus
    # Logs → structured JSON
    ...
```

### 4.4 API Endpoints

**File**: `backend/app/api/v1/endpoints/analytics.py`

```
GET    /api/v1/analytics/requests          — Request log (paginated, filterable)
GET    /api/v1/analytics/requests/{id}     — Single request trace
GET    /api/v1/analytics/errors            — Error summary
GET    /api/v1/analytics/latency           — Latency stats
GET    /api/v1/analytics/features          — Feature usage breakdown
GET    /api/v1/analytics/providers         — Provider performance comparison
```

### 4.5 Frontend Files

#### `frontend/src/app/(dashboard)/settings/analytics/page.tsx` — Analytics dashboard
- Request volume chart
- Error rate chart
- Latency distribution (histogram)
- Provider comparison table
- Feature usage breakdown

### 4.6 Tests

**File**: `backend/tests/services/test_usage_tracker.py`
```python
async def test_log_request(db): ...
async def test_error_rate_calculation(db): ...
async def test_latency_percentiles(db): ...
```

**File**: `backend/tests/middleware/test_observability.py`
```python
def test_request_id_propagation(): ...
def test_structured_logging(): ...
```

---

## Phase 5: Frontend Dashboard & Polish

**Goal**: Comprehensive frontend for all new features, unified navigation.

**Duration**: ~3-4 days

### 5.1 New Pages

| Route | Page | Description |
|-------|------|-------------|
| `/settings/providers` | Provider Registry | Manage providers, toggle, capabilities |
| `/settings/usage` | Usage Dashboard | Cost summaries, trends, breakdowns |
| `/settings/budgets` | Budget Management | Cost limits, alerts |
| `/settings/health` | Health Monitor | Provider status, circuit breakers |
| `/settings/analytics` | Analytics | Request logs, latency, errors |
| `/settings/routing` | Model Routing | Feature routing rules, recommendations |

### 5.2 Sidebar Update

**File**: `frontend/src/components/layout/sidebar.tsx`

```typescript
const bottomLinks = [
  { href: '/settings/api-keys', label: 'API Keys', icon: KeyIcon },
  { href: '/settings/providers', label: 'Providers', icon: ServerIcon },
  { href: '/settings/usage', label: 'Usage', icon: ChartBarIcon },
  { href: '/settings/budgets', label: 'Budgets', icon: WalletIcon },
  { href: '/settings/health', label: 'Health', icon: HeartPulseIcon },
  { href: '/settings/analytics', label: 'Analytics', icon: ActivityIcon },
];
```

### 5.3 Shared Components

#### `frontend/src/components/providers/provider-card.tsx`
- Provider status, capabilities badges, toggle switch

#### `frontend/src/components/usage/cost-chart.tsx`
- Recharts-based cost trend visualization

#### `frontend/src/components/usage/budget-progress.tsx`
- Progress bar with threshold alerts

#### `frontend/src/components/health/status-badge.tsx`
- Green/yellow/red health indicator

#### `frontend/src/components/analytics/request-table.tsx`
- Sortable, filterable request log table

### 5.4 Layout Updates

**File**: `frontend/src/app/(dashboard)/layout.tsx`
- Add settings sub-navigation tabs

### 5.5 Tests

**File**: `frontend/src/__tests__/providers-page.test.tsx`
**File**: `frontend/src/__tests__/usage-page.test.tsx`
**File**: `frontend/src/__tests__/health-page.test.tsx`

---

## Complete File Manifest

### Backend — New Files

```
backend/app/models/provider.py
backend/app/models/health.py
backend/app/models/token_usage.py
backend/app/models/observability.py

backend/app/services/provider_registry.py
backend/app/services/api_key_manager.py
backend/app/services/token_manager.py
backend/app/services/cost_estimator.py
backend/app/services/health_monitor.py
backend/app/services/retry_failover.py
backend/app/services/model_router.py
backend/app/services/usage_tracker.py

backend/app/schemas/provider.py
backend/app/schemas/usage.py
backend/app/schemas/health.py
backend/app/schemas/analytics.py

backend/app/api/v1/endpoints/providers.py
backend/app/api/v1/endpoints/usage.py
backend/app/api/v1/endpoints/health.py
backend/app/api/v1/endpoints/routing.py
backend/app/api/v1/endpoints/analytics.py

backend/app/middleware/observability.py
backend/app/core/tracing.py

backend/alembic/versions/20260716_1100_provider_registry.py
backend/alembic/versions/20260716_1200_token_usage_cost.py
backend/alembic/versions/20260716_1300_health_failover.py
backend/alembic/versions/20260716_1400_observability.py
```

### Backend — Modified Files

```
backend/app/models/__init__.py          — Register new models
backend/app/api/v1/router.py            — Register new routers
backend/app/orchestrator/orchestrator.py — Major refactor
backend/app/orchestrator/models.py      — Add ModelRoute, etc.
backend/app/models/api_key.py           — Add ApiKeyHealth relationship
backend/app/services/api_key_service.py — Delegate to ApiKeyManager
backend/app/api/v1/endpoints/api_keys.py — Add rotate/validate-all/health
backend/app/core/config.py              — Add observability settings
backend/app/core/constants.py           — Add new constants
```

### Frontend — New Files

```
frontend/src/app/(dashboard)/settings/providers/page.tsx
frontend/src/app/(dashboard)/settings/usage/page.tsx
frontend/src/app/(dashboard)/settings/budgets/page.tsx
frontend/src/app/(dashboard)/settings/health/page.tsx
frontend/src/app/(dashboard)/settings/analytics/page.tsx
frontend/src/app/(dashboard)/settings/routing/page.tsx

frontend/src/components/providers/provider-card.tsx
frontend/src/components/usage/cost-chart.tsx
frontend/src/components/usage/budget-progress.tsx
frontend/src/components/usage/usage-table.tsx
frontend/src/components/health/status-badge.tsx
frontend/src/components/health/circuit-breaker-card.tsx
frontend/src/components/analytics/request-table.tsx
frontend/src/components/analytics/latency-chart.tsx
```

### Frontend — Modified Files

```
frontend/src/lib/api.ts                — Add all new API methods/types
frontend/src/components/layout/sidebar.tsx — Add new nav links
frontend/src/app/(dashboard)/layout.tsx — Settings sub-nav
frontend/src/app/(dashboard)/settings/api-keys/page.tsx — Enhance
```

### Test Files

```
backend/tests/services/test_provider_registry.py
backend/tests/services/test_api_key_manager.py
backend/tests/services/test_token_manager.py
backend/tests/services/test_cost_estimator.py
backend/tests/services/test_health_monitor.py
backend/tests/services/test_retry_failover.py
backend/tests/services/test_model_router.py
backend/tests/services/test_usage_tracker.py
backend/tests/middleware/test_observability.py
backend/tests/api/test_providers.py
backend/tests/api/test_usage.py
backend/tests/api/test_health.py
backend/tests/api/test_analytics.py

frontend/src/__tests__/providers-page.test.tsx
frontend/src/__tests__/usage-page.test.tsx
frontend/src/__tests__/health-page.test.tsx
frontend/src/__tests__/analytics-page.test.tsx
```

---

## Testing Strategy

### Backend Unit Tests (pytest + pytest-asyncio)

| Layer | Focus | Tools |
|-------|-------|-------|
| Models | CRUD, constraints, relationships | pytest, factory_boy |
| Services | Business logic, DB interactions | pytest-asyncio, test DB fixtures |
| API Endpoints | Request/response contracts | httpx AsyncClient |
| Orchestrator | Routing, failover, cost | Mock LLM responses |

### Backend Integration Tests

| Scenario | Approach |
|----------|----------|
| Full LLM pipeline | Mock litellm, verify DB writes |
| Circuit breaker | Simulate failures, verify state transitions |
| Failover chain | Mock provider failures, verify fallback |
| Budget enforcement | Set budget, exceed, verify rejection |

### Frontend Tests

| Layer | Tools |
|-------|-------|
| Components | React Testing Library |
| Pages | Playwright E2E (manual) |
| API integration | MSW (Mock Service Worker) |

### Test Configuration

**File**: `backend/tests/conftest.py`
```python
@pytest.fixture
async def db():
    """Isolated test DB session with rollback."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        yield session
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
def mock_llm():
    """Mock LiteLLM completion."""
    with patch("app.ai.llm.completion") as mock:
        mock.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="test"))])
        yield mock
```

---

## Migration Execution Order

```
1. alembic upgrade head  → Creates all 4 new migration tables
2. Seed provider_registry with 10 providers
3. Deploy backend with new services
4. Deploy frontend with new pages
5. Run validation: POST /api/v1/api-keys/validate-all
6. Verify: GET /api/v1/health/providers
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Migration data loss | Back up DB before each migration |
| Breaking existing orchestrator | Feature-flag new orchestrator, keep old as fallback |
| Performance regression | Async everything, connection pooling, indexes |
| Cost explosion | Budget enforcement before any LLM call |
| Key exposure | Never log raw keys, Fernet encryption at rest |

---

## Dependencies

### Python Packages (new)
```
opentelemetry-api>=1.20
opentelemetry-sdk>=1.20
opentelemetry-exporter-otlp>=1.20
prometheus-client>=0.17
```

### npm Packages (new)
```
recharts           # Charts
@radix-ui/react-*  # UI primitives (via shadcn)
date-fns           # Date utilities
```

---

## Success Criteria

- [ ] 10 providers registered and selectable
- [ ] API key rotation works atomically
- [ ] Health status visible for all providers
- [ ] Circuit breaker opens/closes correctly
- [ ] Failover chains work (user keys → system fallback)
- [ ] Token usage persisted to DB after every request
- [ ] Cost estimates match provider pricing
- [ ] Budget enforcement blocks over-spend
- [ ] Usage dashboard shows real-time data
- [ ] Analytics page shows request logs
- [ ] All existing tests pass
- [ ] New tests cover ≥80% of new code
