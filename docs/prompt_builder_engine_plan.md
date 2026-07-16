# Revora Prompt Builder Engine — Implementation Plan

## 1. Architecture Overview

```
prompt_engine/
├── __init__.py                    # Module exports, singleton wiring
├── models.py                      # All dataclass domain models (expanded)
├── builder.py                     # Core PromptBuilder orchestrator (rewritten)
├── templates.py                   # Template registry (rewritten)
├── sections/                      # 14 prompt section builders
│   ├── __init__.py
│   ├── base.py                    # BasePromptSection ABC
│   ├── system_identity.py         # System identity/persona
│   ├── repo_context.py            # Repository summary
│   ├── architecture_context.py    # Architecture pattern/structure
│   ├── conventions_context.py     # Coding conventions
│   ├── rules_context.py           # Review rules
│   ├── changed_files.py           # Diff content (changed files)
│   ├── related_files.py           # Related/import graph files
│   ├── test_files.py              # Test coverage context
│   ├── security_context.py        # Security findings context
│   ├── api_endpoints.py           # API endpoint context
│   ├── db_schemas.py              # Database schema context
│   ├── documentation.py           # Documentation context
│   ├── historical_context.py      # Git history/blame context
│   ├── impact_analysis.py         # Impact analysis context
│   ├── config_files.py            # Configuration files context
│   ├── static_analysis.py         # Static analysis results
│   ├── analysis_instructions.py   # Per-type analysis instructions
│   └── output_format.py           # Output format specification
├── budgeting/                     # Token budget allocation
│   ├── __init__.py
│   └── allocator.py               # PromptBudgetAllocator
├── cache/                         # Prompt caching
│   ├── __init__.py
│   └── prompt_cache.py            # PromptCacheService
├── compression/                   # Prompt compression
│   ├── __init__.py
│   └── prompt_compressor.py       # PromptCompressor
├── versioning/                    # Prompt versioning
│   ├── __init__.py
│   └── version_manager.py         # PromptVersionManager
├── explainability/                # Explainability annotations
│   ├── __init__.py
│   └── annotator.py               # PromptAnnotator
└── observability/                 # Metrics and tracing
    ├── __init__.py
    └── metrics.py                 # PromptMetricsCollector
```

---

## 2. Database Schema (5 Tables)

### 2.1 `prompt_templates` — Stores prompt template definitions

```sql
CREATE TABLE prompt_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,           -- 'pr_review', 'repo_review', etc.
    review_type VARCHAR(50) NOT NULL,     -- enum: pr_review, repo_review, ...
    system_prompt TEXT NOT NULL,
    section_order JSONB NOT NULL DEFAULT '[]',  -- ordered list of section names
    section_defaults JSONB NOT NULL DEFAULT '{}', -- default params per section
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE UNIQUE INDEX idx_prompt_templates_name ON prompt_templates(name);
CREATE INDEX idx_prompt_templates_type ON prompt_templates(review_type);
```

### 2.2 `prompt_versions` — Immutable version snapshots

```sql
CREATE TABLE prompt_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    system_prompt TEXT NOT NULL,
    section_config JSONB NOT NULL,        -- full section config snapshot
    hash VARCHAR(64) NOT NULL,            -- content hash for dedup
    is_current BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),

    UNIQUE(template_id, version_number)
);

CREATE INDEX idx_prompt_versions_template ON prompt_versions(template_id);
CREATE INDEX idx_prompt_versions_hash ON prompt_versions(hash);
```

### 2.3 `prompt_cache` — Compiled prompt cache

```sql
CREATE TABLE prompt_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cache_key VARCHAR(64) NOT NULL UNIQUE, -- SHA-256 of (template_hash + context_hash)
    template_id UUID NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES prompt_versions(id) ON DELETE CASCADE,
    context_hash VARCHAR(64) NOT NULL,     -- hash of input context data
    compiled_prompt JSONB NOT NULL,        -- serialized CompiledPrompt
    total_tokens INTEGER NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_hit_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_prompt_cache_key ON prompt_cache(cache_key);
CREATE INDEX idx_prompt_cache_template ON prompt_cache(template_id);
CREATE INDEX idx_prompt_cache_expires ON prompt_cache(expires_at);
```

### 2.4 `prompt_metrics` — Per-compilation metrics

```sql
CREATE TABLE prompt_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    template_id UUID NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,
    version_id UUID REFERENCES prompt_versions(id) ON DELETE SET NULL,
    review_type VARCHAR(50) NOT NULL,
    total_tokens INTEGER NOT NULL,
    section_tokens JSONB NOT NULL DEFAULT '{}',  -- {section_name: token_count}
    cache_hit BOOLEAN NOT NULL DEFAULT false,
    compression_ratio FLOAT,
    compression_applied BOOLEAN NOT NULL DEFAULT false,
    budget_label VARCHAR(10) NOT NULL DEFAULT '16K',
    compilation_time_ms FLOAT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_prompt_metrics_review ON prompt_metrics(review_id);
CREATE INDEX idx_prompt_metrics_template ON prompt_metrics(template_id);
```

### 2.5 `token_usage` — Aggregated token usage tracking

```sql
CREATE TABLE token_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    template_id UUID REFERENCES prompt_templates(id) ON DELETE SET NULL,
    review_type VARCHAR(50) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    prompt_tokens INTEGER NOT NULL,        -- input tokens from prompt specifically
    context_tokens INTEGER NOT NULL,       -- tokens from retrieval context
    system_tokens INTEGER NOT NULL,        -- tokens from system prompt
    estimated_cost_usd FLOAT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_token_usage_review ON token_usage(review_id);
CREATE INDEX idx_token_usage_type ON token_usage(review_type);
CREATE INDEX idx_token_usage_provider ON token_usage(provider);
```

---

## 3. Interface Definitions

### 3.1 Core Models (`models.py`)

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

class ReviewType(str, Enum):
    PR_REVIEW = "pr_review"
    REPO_REVIEW = "repo_review"
    SECURITY_REVIEW = "security_review"
    PERFORMANCE_REVIEW = "performance_review"
    ARCHITECTURE_REVIEW = "architecture_review"
    TESTING_REVIEW = "testing_review"
    DOCUMENTATION_REVIEW = "documentation_review"
    PATCH_GENERATION = "patch_generation"
    EXPLAINABILITY = "explainability"
    REPOSITORY_CHAT = "repository_chat"

class SectionPriority(int, Enum):
    CRITICAL = 0    # Must always be included
    HIGH = 1        # Included unless severely budget-constrained
    MEDIUM = 2      # Included when budget allows
    LOW = 3         # Only with generous budgets

@dataclass
class PromptSection:
    name: str
    content: str
    token_count: int = 0
    priority: SectionPriority = SectionPriority.MEDIUM
    version: str = "1.0"
    metadata: dict = field(default_factory=dict)
    compressed: bool = False
    source_bucket: str = ""  # maps to RetrievalResult bucket

@dataclass
class SectionConfig:
    name: str
    enabled: bool = True
    max_tokens: int = 2000
    priority: SectionPriority = SectionPriority.MEDIUM
    template_params: dict = field(default_factory=dict)

@dataclass
class PromptBuildRequest:
    review_type: ReviewType
    repo_summary: str = ""
    architecture_summary: str = ""
    conventions: str = ""
    rules: list[str] = field(default_factory=list)
    diff_content: str = ""
    related_files: list[dict] = field(default_factory=list)
    test_files: list[dict] = field(default_factory=list)
    security_context: list[dict] = field(default_factory=list)
    api_endpoints: list[dict] = field(default_factory=list)
    db_schemas: list[dict] = field(default_factory=list)
    impact_context: list[dict] = field(default_factory=list)
    historical_context: list[dict] = field(default_factory=list)
    documentation_context: list[dict] = field(default_factory=list)
    config_files: list[dict] = field(default_factory=list)
    static_analysis: str = ""
    budget_label: str = "16K"
    model_context_window: int = 16000
    section_overrides: dict = field(default_factory=dict)
    enable_compression: bool = True
    enable_caching: bool = True
    explainability: bool = False

@dataclass
class CompiledPrompt:
    version: str = "2.0"
    review_type: ReviewType = ReviewType.PR_REVIEW
    template_id: Optional[str] = None
    version_id: Optional[str] = None
    sections: Dict[str, PromptSection] = field(default_factory=dict)
    section_order: list[str] = field(default_factory=list)
    system_prompt: str = ""
    user_prompt: str = ""
    total_tokens: int = 0
    cache_key: str = ""
    explainability_notes: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def get_user_messages(self) -> list[dict]:
        messages = [{"role": "system", "content": self.system_prompt}]
        if self.user_prompt:
            messages.append({"role": "user", "content": self.user_prompt})
        return messages

@dataclass
class PromptBuildResult:
    compiled_prompt: CompiledPrompt
    cache_hit: bool = False
    compression_applied: bool = False
    compression_ratio: float = 1.0
    compilation_time_ms: float = 0.0
    section_tokens: dict = field(default_factory=dict)
    explainability_notes: list[str] = field(default_factory=list)
```

### 3.2 Section Builder Interface (`sections/base.py`)

```python
from abc import ABC, abstractmethod
from app.prompt_engine.models import PromptSection, SectionPriority

class BasePromptSection(ABC):
    """Base class for all prompt section builders."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique section identifier (e.g., 'changed_files', 'security_context')."""
        ...

    @property
    def priority(self) -> SectionPriority:
        return SectionPriority.MEDIUM

    @property
    def default_max_tokens(self) -> int:
        return 2000

    @abstractmethod
    async def build(self, request: 'PromptBuildRequest', token_budget: int) -> PromptSection | None:
        """Build the section content. Return None if section should be skipped."""
        ...

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    async def safe_build(self, request: 'PromptBuildRequest', token_budget: int) -> PromptSection | None:
        try:
            return await self.build(request, token_budget)
        except Exception:
            return None
```

### 3.3 Budget Allocator Interface

```python
@dataclass
class PromptBudget:
    total: int
    system_tokens: int = 0
    section_allocations: dict[str, int] = field(default_factory=dict)
    section_used: dict[str, int] = field(default_factory=dict)
    output_buffer: int = 2000

    @property
    def remaining(self) -> int:
        used = sum(self.section_used.values()) + self.system_tokens
        return self.total - used - self.output_buffer

    def can_fit(self, section: str, tokens: int) -> bool:
        max_allowed = self.section_allocations.get(section, self.total // 4)
        current = self.section_used.get(section, 0)
        return (current + tokens) <= max_allowed and self.remaining >= tokens

    def record(self, section: str, tokens: int) -> None:
        self.section_used[section] = self.section_used.get(section, 0) + tokens
```

---

## 4. File-by-File Breakdown

### Phase 1: Core Models & DB Layer (5 files)

| File | Purpose | Key Changes |
|------|---------|-------------|
| `prompt_engine/models.py` | Expand domain models | Add ReviewType enum, SectionPriority, PromptBuildRequest, SectionConfig, PromptBuildResult. Keep backward-compatible CompiledPrompt.get_user_messages() |
| `models/prompt.py` | New SQLAlchemy models | 5 ORM models inheriting from Base. Register in models/__init__.py |
| `alembic/versions/20260716_1000_prompt_engine_tables.py` | Migration for 5 tables | Follow existing pattern from context_engine migration |
| `core/constants.py` | Add prompt constants | REVIEW_TYPES, DEFAULT_BUDGET_LABEL, PROMPT_CACHE_TTL, SECTION_ORDER defaults |
| `prompt_engine/__init__.py` | Updated exports | Export new PromptBuilder singleton + ReviewType |

### Phase 2: Section Builders (16 files)

| File | Section | Source Bucket(s) |
|------|---------|------------------|
| `sections/__init__.py` | Registry + factory | — |
| `sections/base.py` | BasePromptSection ABC | — |
| `sections/system_identity.py` | System prompt per review type | Static |
| `sections/repo_context.py` | Repository summary | Intelligence data |
| `sections/architecture_context.py` | Architecture pattern | Intelligence data |
| `sections/conventions_context.py` | Coding conventions | Knowledge store |
| `sections/rules_context.py` | Review rules | Knowledge store |
| `sections/changed_files.py` | Diff content | RetrievalResult.changed_files |
| `sections/related_files.py` | Related files | RetrievalResult.related_files |
| `sections/test_files.py` | Test coverage | RetrievalResult.test_files |
| `sections/security_context.py` | Security findings | RetrievalResult.security_context |
| `sections/api_endpoints.py` | API endpoints | RetrievalResult.api_endpoints |
| `sections/db_schemas.py` | DB schemas | RetrievalResult.db_schemas |
| `sections/impact_analysis.py` | Impact analysis | RetrievalResult.impact_context |
| `sections/documentation.py` | Documentation | RetrievalResult.documentation_context |
| `sections/historical_context.py` | Git history | RetrievalResult.historical_context |
| `sections/config_files.py` | Config files | RetrievalResult.config_files |
| `sections/static_analysis.py` | Static analysis | Static analysis results |
| `sections/analysis_instructions.py` | Per-type analysis instructions | ReviewType-dependent |
| `sections/output_format.py` | Output format spec | ReviewType-dependent |

### Phase 3: Budget, Cache, Compression, Versioning (6 files)

| File | Purpose |
|------|---------|
| `budgeting/__init__.py` | Exports |
| `budgeting/allocator.py` | PromptBudgetAllocator: maps ReviewType → section token allocations using existing token_budget_engine presets |
| `cache/__init__.py` | Exports |
| `cache/prompt_cache.py` | PromptCacheService: DB-backed cache using prompt_cache table, TTL-based expiry |
| `compression/__init__.py` | Exports |
| `compression/prompt_compressor.py` | PromptCompressor: applies existing compression strategies to prompt sections |
| `versioning/__init__.py` | Exports |
| `versioning/version_manager.py` | PromptVersionManager: version snapshots, hash-based dedup |

### Phase 4: Explainability & Observability (3 files)

| File | Purpose |
|------|---------|
| `explainability/__init__.py` | Exports |
| `explainability/annotator.py` | PromptAnnotator: adds per-section rationale annotations |
| `observability/__init__.py` | Exports |
| `observability/metrics.py` | PromptMetricsCollector: records to prompt_metrics + token_usage tables |

### Phase 5: Core Builder Rewrite (1 file)

| File | Purpose |
|------|---------|
| `prompt_engine/builder.py` | Complete rewrite. PromptBuilder.compile() now takes PromptBuildRequest, uses section registry, budget allocator, cache, compression, versioning |

### Phase 6: Pipeline Integration (2 files)

| File | Changes |
|------|---------|
| `pipeline/orchestrator.py` | Rewrite `_stage_prompt` to build PromptBuildRequest from all 11 RetrievalResult buckets |
| `prompt_engine/templates.py` | Rewrite as template registry keyed by ReviewType |

---

## 5. Module Architecture — Detailed Design

### 5.1 Section Registry Pattern

```python
# sections/__init__.py
from app.prompt_engine.sections.base import BasePromptSection

_SECTION_REGISTRY: dict[str, type[BasePromptSection]] = {}

def register_section(cls: type[BasePromptSection]) -> type[BasePromptSection]:
    _SECTION_REGISTRY[cls.name] = cls
    return cls

def get_all_sections() -> dict[str, type[BasePromptSection]]:
    return dict(_SECTION_REGISTRY)

def get_sections_for_review(review_type: ReviewType) -> list[BasePromptSection]:
    """Return instantiated sections in priority order for a review type."""
    SECTION_MAP = {
        ReviewType.PR_REVIEW: [
            "system_identity", "repo_context", "architecture_context",
            "conventions_context", "rules_context", "changed_files",
            "related_files", "test_files", "security_context",
            "static_analysis", "analysis_instructions", "output_format",
        ],
        ReviewType.SECURITY_REVIEW: [
            "system_identity", "repo_context", "architecture_context",
            "security_context", "changed_files", "related_files",
            "api_endpoints", "db_schemas", "config_files",
            "static_analysis", "analysis_instructions", "output_format",
        ],
        # ... other ReviewType mappings
    }
    section_names = SECTION_MAP.get(review_type, SECTION_MAP[ReviewType.PR_REVIEW])
    return [_SECTION_REGISTRY[name]() for name in section_names if name in _SECTION_REGISTRY]
```

### 5.2 Template Registry Pattern

```python
# templates.py — rewritten as registry
from app.prompt_engine.models import ReviewType

SYSTEM_PROMPTS = {
    ReviewType.PR_REVIEW: "You are Revora AI, an expert senior software engineer performing a code review...",
    ReviewType.SECURITY_REVIEW: "You are Revora AI, an expert security engineer specializing in OWASP Top 10...",
    ReviewType.PERFORMANCE_REVIEW: "You are Revora AI, an expert performance engineer...",
    ReviewType.ARCHITECTURE_REVIEW: "You are Revora AI, an expert software architect...",
    ReviewType.TESTING_REVIEW: "You are Revora AI, an expert QA engineer...",
    ReviewType.DOCUMENTATION_REVIEW: "You are Revora AI, an expert technical writer...",
    ReviewType.PATCH_GENERATION: "You are Revora AI, an expert developer generating code patches...",
    ReviewType.EXPLAINABILITY: "You are Revora AI, explaining code behavior and design decisions...",
    ReviewType.REPOSITORY_CHAT: "You are Revora AI, a helpful assistant for repository questions...",
    ReviewType.REPO_REVIEW: "You are Revora AI, performing a full repository health review...",
}

ANALYSIS_INSTRUCTIONS = {
    ReviewType.PR_REVIEW: "Review the pull request diff above...",
    ReviewType.SECURITY_REVIEW: "Focus exclusively on security vulnerabilities...",
    # ... per-type instructions
}

OUTPUT_FORMATS = {
    ReviewType.PR_REVIEW: "### Summary\n...\n### Security Findings\n...\n### Bug Findings\n...",
    ReviewType.SECURITY_REVIEW: "### Security Summary\n...\n### Critical Vulnerabilities\n...",
    # ... per-type formats
}
```

### 5.3 PromptBuilder Core Flow

```python
class PromptBuilder:
    async def compile(self, request: PromptBuildRequest) -> PromptBuildResult:
        start = time.time()

        # 1. Resolve template
        template = await self._resolve_template(request.review_type)

        # 2. Version check
        version = await self.version_manager.get_current_version(template.id)

        # 3. Check cache
        if request.enable_caching:
            context_hash = self._hash_context(request)
            cached = await self.prompt_cache.get(template.id, context_hash)
            if cached:
                return PromptBuildResult(compiled_prompt=cached, cache_hit=True, ...)

        # 4. Allocate budget
        budget = self.budget_allocator.allocate(
            request.budget_label, request.model_context_window
        )

        # 5. Build sections
        sections = await self._build_sections(request, budget, template)

        # 6. Compress if needed
        if request.enable_compression and budget.remaining < 0:
            sections = await self.compressor.compress(sections, budget)
            compression_applied = True

        # 7. Assemble prompt
        compiled = self._assemble(request, sections, template)

        # 8. Explainability annotations
        if request.explainability:
            compiled.explainability_notes = self.annotator.annotate(sections, request)

        # 9. Cache result
        if request.enable_caching:
            await self.prompt_cache.set(template.id, context_hash, compiled)

        # 10. Record metrics
        compilation_time_ms = (time.time() - start) * 1000
        await self.metrics.record(request, compiled, compilation_time_ms)

        return PromptBuildResult(
            compiled_prompt=compiled,
            compression_applied=compression_applied,
            compilation_time_ms=compilation_time_ms,
            section_tokens={s.name: s.token_count for s in sections},
        )
```

---

## 6. Phase Order

### Phase 1: Foundation (Days 1-2)
1. Expand `prompt_engine/models.py` with new enums and dataclasses
2. Create `models/prompt.py` with 5 SQLAlchemy models
3. Register models in `models/__init__.py`
4. Create Alembic migration
5. Add constants to `core/constants.py`

### Phase 2: Section System (Days 3-5)
1. Create `sections/base.py` with BasePromptSection ABC
2. Create `sections/__init__.py` with registry and factory
3. Implement all 14 section builders (one per file)
4. Rewrite `templates.py` as template registry
5. Write tests for each section builder

### Phase 3: Budget & Optimization (Days 6-7)
1. Create `budgeting/allocator.py` — maps ReviewType to section allocations
2. Create `compression/prompt_compressor.py` — wraps existing compression engine for prompt sections
3. Create `cache/prompt_cache.py` — DB-backed cache with TTL
4. Create `versioning/version_manager.py` — version snapshots + hash dedup

### Phase 4: Builder Rewrite (Days 8-9)
1. Rewrite `prompt_engine/builder.py` with new PromptBuilder
2. Maintain backward-compatible `prompt_builder` singleton
3. Ensure `CompiledPrompt.get_user_messages()` still works for LLM orchestrator
4. Integration test with mock RetrievalResult

### Phase 5: Pipeline Integration (Day 10)
1. Rewrite `_stage_prompt` in `pipeline/orchestrator.py`
2. Build PromptBuildRequest from all 11 RetrievalResult buckets
3. Add SSE events for new stages (section building, budget allocation, compression)
4. End-to-end test with full pipeline

### Phase 6: Observability & Polish (Days 11-12)
1. Create `explainability/annotator.py`
2. Create `observability/metrics.py`
3. Record to prompt_metrics + token_usage tables
4. Add observability SSE events
5. Final integration tests

---

## 7. Pipeline Integration Changes

### Current `_stage_prompt` (orchestrator.py:309-339)

Only extracts `related_files` from RetrievalResult:
```python
related_files_data = [
    {"file_path": r.file_path, "content": r.content[:1000]}
    for r in retrieval_result.related_files
]
```

### New `_stage_prompt`

```python
async def _stage_prompt(self, emitter, intelligence_data, conventions, rules,
                        diff_content, retrieval_result):
    await emitter.emit("building_prompt", "running", EventType.STAGE_START)

    try:
        # Build PromptBuildRequest from ALL retrieval buckets
        request = PromptBuildRequest(
            review_type=ReviewType.PR_REVIEW,  # or from config
            repo_summary=str(intelligence_data),
            architecture_summary=intelligence_data.get("architecture", {}).get("pattern", "")
                if intelligence_data else "",
            conventions=conventions,
            rules=rules,
            diff_content=sanitize_content(diff_content),
        )

        if retrieval_result:
            request.related_files = [
                {"file_path": r.file_path, "content": r.content[:1000]}
                for r in retrieval_result.related_files
            ]
            request.test_files = [
                {"file_path": r.file_path, "content": r.content[:1000]}
                for r in retrieval_result.test_files
            ]
            request.security_context = [
                {"file_path": r.file_path, "content": r.content[:1000]}
                for r in retrieval_result.security_context
            ]
            request.api_endpoints = [
                {"file_path": r.file_path, "content": r.content[:1000]}
                for r in retrieval_result.api_endpoints
            ]
            request.db_schemas = [
                {"file_path": r.file_path, "content": r.content[:1000]}
                for r in retrieval_result.db_schemas
            ]
            request.impact_context = [
                {"file_path": r.file_path, "content": r.content[:1000]}
                for r in retrieval_result.impact_context
            ]
            request.historical_context = [
                {"file_path": r.file_path, "content": r.content[:1000]}
                for r in retrieval_result.historical_context
            ]
            request.documentation_context = [
                {"file_path": r.file_path, "content": r.content[:1000]}
                for r in retrieval_result.documentation_context
            ]
            request.config_files = [
                {"file_path": r.file_path, "content": r.content[:1000]}
                for r in retrieval_result.config_files
            ]

        result = await prompt_builder.compile(request)

        await emitter.emit("building_prompt", "completed", metrics={
            "tokens": result.compiled_prompt.total_tokens,
            "cache_hit": result.cache_hit,
            "compression_applied": result.compression_applied,
            "compilation_time_ms": result.compilation_time_ms,
            "section_tokens": result.section_tokens,
        })
        return result.compiled_prompt
    except Exception as e:
        logger.warning(f"Prompt building failed: {e}")
        await emitter.emit("building_prompt", "failed", EventType.STAGE_FAILED,
                         message=str(e))
        raise
```

---

## 8. Backward Compatibility

The LLM orchestrator (`app/orchestrator/orchestrator.py:60`) calls `prompt.get_user_messages()`. The new `CompiledPrompt` preserves this interface exactly:

```python
def get_user_messages(self) -> list[dict]:
    messages = [{"role": "system", "content": self.system_prompt}]
    if self.user_prompt:
        messages.append({"role": "user", "content": self.user_prompt})
    return messages
```

The `prompt_engine/__init__.py` continues to export `prompt_builder` singleton. The pipeline's `_stage_prompt` returns `result.compiled_prompt` (a `CompiledPrompt`) so downstream code is unchanged.

---

## 9. Test Strategy

### Unit Tests

| Test File | Coverage |
|-----------|----------|
| `tests/test_prompt_models.py` | ReviewType enum, SectionPriority, PromptBuildRequest validation, CompiledPrompt.get_user_messages() |
| `tests/test_section_builders.py` | Each section builder: builds correctly, returns None when data missing, respects token budget |
| `tests/test_section_registry.py` | Registry: all sections registered, get_sections_for_review returns correct sets, priority ordering |
| `tests/test_prompt_budget.py` | Budget allocation per ReviewType, can_fit/record, overflow handling |
| `tests/test_prompt_cache.py` | Cache hit/miss, TTL expiry, context_hash-based keying, invalidation |
| `tests/test_prompt_compressor.py` | Compression reduces tokens, preserves critical sections, compression_ratio calculation |
| `tests/test_prompt_versioning.py` | Version increment, hash dedup, is_current flag |
| `tests/test_prompt_annotator.py` | Explainability annotations per section |
| `tests/test_prompt_metrics.py` | Metrics recording to DB, token_usage tracking |
| `tests/test_prompt_builder.py` | Full builder flow: compile with all data, compile with missing data, cache round-trip |

### Integration Tests

| Test File | Coverage |
|-----------|----------|
| `tests/test_prompt_pipeline_integration.py` | `_stage_prompt` with mock RetrievalResult (all 11 buckets), verify all sections populated |
| `tests/test_prompt_backward_compat.py` | CompiledPrompt works with existing LLM orchestrator, prompt_builder singleton import |

### Test Patterns (following existing conftest.py)
- Use `pytest` with `async def test_*` methods
- Use in-memory SQLite via `test_db` fixture
- Mock RetrievalResult with all 11 buckets populated
- Assert on token counts, section presence, cache behavior
- Follow existing naming: `TestClassName` with `async def test_*` methods

---

## 10. Key Design Decisions

1. **Backward compatibility**: `CompiledPrompt.get_user_messages()` interface unchanged. LLM orchestrator needs zero changes.

2. **Section priority system**: Each section declares priority (CRITICAL/HIGH/MEDIUM/LOW). Budget allocator uses priority to decide which sections to include/exclude when budget is tight.

3. **Lazy section building**: Sections are built only if their data is available and budget allows. Missing data → section returns None → excluded from prompt.

4. **ReviewType-driven**: Section composition varies by ReviewType. Security review emphasizes security_context, api_endpoints, db_schemas. PR review emphasizes changed_files, related_files, test_files.

5. **Cache key composition**: `SHA256(template_hash + context_hash)` where context_hash covers all input data. Same inputs → same prompt → cache hit.

6. **Compression integration**: Uses existing CompressionEngine strategies (dedup, truncation, import_prune, symbol_merge) applied to assembled prompt sections, not individual files.

7. **5 DB tables, not 6**: token_usage table separates prompt tokens from LLM input/output tokens for fine-grained tracking. prompt_metrics captures compilation-side metrics.

8. **Existing token_budget_engine reuse**: The new PromptBudgetAllocator wraps existing TokenBudgetEngine presets (4K–128K) and maps them to per-section allocations for each ReviewType.
