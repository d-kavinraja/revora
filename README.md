<div align="center">

<img src="https://img.shields.io/badge/Revora-AI%20Code%20Review-6366f1?style=for-the-badge&logo=github&logoColor=white" alt="Revora Banner" />

# **Revora**

### The Open-Source AI Code Review Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-6366f1?style=flat-square)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169e1?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ed?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![GitHub stars](https://img.shields.io/github/stars/d-kavinraja/revora?style=flat-square&color=facc15)](https://github.com/d-kavinraja/revora/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/d-kavinraja/revora?style=flat-square)](https://github.com/d-kavinraja/revora/network/members)
[![GitHub issues](https://img.shields.io/github/issues/d-kavinraja/revora?style=flat-square&color=ef4444)](https://github.com/d-kavinraja/revora/issues)

---

**Revora** is an **Open-Source AI Code Review Platform** built to deliver intelligent, repository-aware code reviews. Instead of reviewing only pull request diffs, Revora understands the repository by analyzing its architecture, dependencies, code relationships, conventions, and developer intent before generating AI-powered feedback.

Designed with enterprise-grade engineering in mind, Revora combines repository intelligence, code graph indexing, smart context retrieval, multi-LLM orchestration, and a verification engine to produce accurate, explainable, and trustworthy code reviews.

</div>

---

## Table of Contents

- [Why Revora?](#why-revora)
- [Architecture Overview](#architecture-overview)
- [Review Pipeline Flow](#review-pipeline-flow)
- [Feature Status](#feature-status)
- [Supported LLM Providers](#supported-llm-providers)
- [Context Engineering Modules](#context-engineering-modules)
- [Repository Intelligence Engine](#repository-intelligence-engine)
- [Context Retrieval Documentation](#context-retrieval-documentation)
- [Technology Stack](#technology-stack)
- [Folder Structure](#folder-structure)
- [Quick Start](#quick-start)
- [Local Development Guide](#local-development-guide)
- [Environment Variables](#environment-variables)
- [GitHub OAuth Setup](#github-oauth-setup)
- [GitHub App Setup](#github-app-setup)
- [GitHub Permissions](#github-permissions)
- [Webhook Configuration](#webhook-configuration)
- [Database Setup](#database-setup)
- [Redis (Optional)](#redis-optional)
- [Docker Setup](#docker-setup)
- [Running the Application](#running-the-application)
- [Authentication Flow](#authentication-flow)
- [Review Workflow](#review-workflow)
- [API Documentation](#api-documentation)
- [Contributing](#contributing)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Development Best Practices](#development-best-practices)
- [License](#license)

---

## Why Revora?

<table>
<tr>
<td width="50%" valign="top">

### The Problem

Current AI code review tools:
- Read only the diff — no repository context
- Produce generic, low-confidence feedback
- Hallucinate file paths and code references
- Cannot understand architecture or conventions
- Act as black boxes with no explainability

</td>
<td width="50%" valign="top">

### The Revora Solution

Revora's Context Engineering Engine:
- Analyzes the **entire repository** structure
- Builds **code graphs** (imports, calls, modules, APIs)
- Retrieves **only relevant context** for each change
- **Verifies every finding** against actual code
- Supports **per-repository model configuration**

</td>
</tr>
</table>

---

## Architecture Overview

```mermaid
graph TB
    subgraph Frontend["Frontend - Next.js 16 + Tailwind CSS"]
        UI[Dashboard, Repos, Reviews]
        ConfigModal[Repository Model Config]
    end

    subgraph Backend["Backend - FastAPI + SQLAlchemy"]
        WH[Webhook Receiver]
        API[REST API Endpoints]
    end

    subgraph ContextEngine["Context Engineering Engine"]
        direction TB
        I1["Repository Intelligence - Language, Framework, Architecture, DB, CI/CD Detection"]
        I2["Repository Indexing - Import Graph, Call Graph, Module Graph, API Graph, DB Graph"]
        I3["Knowledge Base - Conventions, Rules, Summaries (PostgreSQL)"]
        I4["Context Retrieval - RAG, Ranking, Compression, Token Budgeting"]
        I5["Prompt Builder - Modular, Versioned Prompts"]
        I6["LLM Orchestrator - Multi-Provider with Fallbacks, Retries, Cost Tracking"]
        I7["Verification Engine - File/Line Existence, Hallucination Detection, Confidence Scoring"]
        I8["GitHub Review Generator - Risk Scoring, Inline Comments, PR Summary"]
    end

    subgraph Security["Security Layer"]
        SEC[Secret Redaction]
        INJ[Prompt Injection Detection]
    end

    subgraph Data["Data Layer"]
        PG[(PostgreSQL 15)]
        MC[(Memory Cache)]
        RC{Redis 7 - Optional}
    end

    style RC fill:#ffe0e0,stroke:#ff4444

    subgraph External["External Services"]
        GH[GitHub API - Webhooks, PR Reviews, Check Runs]
        LLM[11+ Providers via BYOK Orchestrator]
    end

    UI <--> API
    ConfigModal --> API
    WH --> I1
    I1 --> I2 --> I3 --> I4 --> I5 --> I6 --> I7 --> I8
    SEC --> I4
    INJ --> I4
    API <--> PG
    MC -.-> I4
    RC -.-> I4
    I8 <--> GH
    I6 <--> LLM
```

---

## Review Pipeline Flow

```mermaid
sequenceDiagram
    participant GH as GitHub
    participant WH as Webhook
    participant INT as Intelligence Engine
    participant IDX as Indexer
    participant KB as Knowledge Base
    participant RET as Retriever
    participant PROM as Prompt Builder
    participant ORCH as LLM Orchestrator
    participant VER as Verifier
    participant GEN as Review Generator
    participant SEC as Security Layer

    GH->>WH: PR Opened / Reopened
    WH->>WH: Verify HMAC Signature
    WH->>INT: Phase 1: Analyze Repository

    Note over INT: Detect languages, frameworks,<br/>architecture, DB, CI/CD, security patterns

    INT->>IDX: Phase 2: Build Code Graphs

    Note over IDX: Import graph, call graph,<br/>module graph, API graph,<br/>DB models, config, tests

    IDX->>KB: Phase 3: Load Knowledge Base

    Note over KB: Conventions, review rules,<br/>cached summaries

    KB->>RET: Phase 4: Retrieve Relevant Context

    Note over RET: RAG retrieval from graphs,<br/>ranking, compression,<br/>token budgeting (5k-12k)

    RET->>SEC: Sanitize Content
    SEC->>SEC: Redact secrets, detect injection
    SEC->>PROM: Phase 5: Build Prompt

    Note over PROM: System prompt + repo context<br/>+ diff + related files<br/>+ analysis instructions

    PROM->>ORCH: Phase 6: Call LLM Provider

    Note over ORCH: Multi-provider fallback,<br/>retries, cost tracking

    ORCH->>VER: Phase 7: Verify Findings

    Note over VER: File exists? Line exists?<br/>Hallucination check?<br/>Confidence scoring

    VER->>GEN: Phase 8: Generate GitHub Review

    Note over GEN: Risk scoring, inline comments,<br/>PR summary, suggested fixes

    GEN->>GH: Publish Review via API
```

---

## Feature Status

<table>
<tr>
<td width="50%" valign="top">

### Completed

**Backend - Context Engineering Engine:**
- Repository Intelligence Engine (17 detectors)
- Repository Indexing (7 code graphs)
- Knowledge Base with PostgreSQL persistence
- Context Retrieval Engine — 13 specialized retrievers, 6-factor ranking, 5-stage compression pipeline, configurable token budgets (4K–128K), multi-layer caching (in-memory LRU + optional Redis), 5-stage fallback chain, graph traversal (BFS/DFS/k-hop/shortest path)
- Modular Prompt Builder
- Multi-Provider LLM Orchestrator (Gemini available; OpenAI, Anthropic, Groq, DeepSeek, Grok, OpenRouter, Azure OpenAI, Ollama, Cohere, Mistral in development)
- Verification Engine (file/line checks, hallucination detection)
- GitHub Review Generator (inline comments, risk scoring)
- Security layer (secret redaction, prompt injection detection)
- SSE real-time event emitter
- Repository-level model configuration

**Backend - BYOK LLM Orchestrator:**
- Provider Registry & Management (CRUD for LLM providers)
- Token Usage Tracking with real cost estimation
- Health Monitoring & Failover logging
- Intelligent Model Router (multi-model routing strategies)
- Retry & Failover (circuit breaker, exponential backoff)
- Analytics & Observability (LLM request logging)
- Model Discovery Engine (dynamic model listing per provider)

**Backend - Core:**
- GitHub App authentication (JWT + installation tokens)
- GitHub OAuth login flow
- Webhook receiver with HMAC verification
- Review pipeline with 8-phase execution
- Alembic migrations (9 migrations, 25+ tables)

**Frontend:**
- Landing page with hero and features
- GitHub OAuth login
- Dashboard with stats and recent reviews
- Repositories page with model configuration modal
- Reviews list with status filters
- Review detail with markdown rendering
- Settings: API keys management with test/rotate/health
- Settings: Provider management
- Settings: Usage analytics dashboard
- Settings: Health monitoring
- Settings: LLM routing configuration
- Settings: Platform analytics
- Light/dark mode toggle
- Responsive sidebar with collapse
- Shared components (StatusBadge, Skeleton, EmptyState)

</td>
<td width="50%" valign="top">

### In Development 

**AI Capabilities:**
- Auto-remediation (generating fix commits)
- Conversational PR interface (Chat with PR)
- PR description auto-generation

**GitHub Integration:**
- GitHub Checks API (pass/fail status checks)
- Inline code annotations on PR diffs

**Context Engineering:**
- Cross-repository context (microservices)
- Tree-sitter based AST parsing (currently regex-based)

**Review Quality:**
- Developer feedback loop (upvote/downvote comments)
- Review accuracy improvement from feedback

**Enterprise:**
- Role-Based Access Control (RBAC)
- SSO/SAML integration
- Audit logging

**Frontend:**
- Real-time SSE execution dashboard on review detail page

</td>
</tr>
</table>

---

## Bring-Your-Own-Key (BYOK) LLM Orchestrator

The **BYOK LLM Orchestrator** is a production-grade multi-provider LLM routing and management system built into Revora. It consists of several integrated services:

### Provider Registry & Management
- CRUD operations for LLM providers with encrypted API key storage
- Supports **11 providers**: Gemini, OpenAI, Anthropic, Groq, DeepSeek, Grok, OpenRouter, Azure OpenAI, Ollama, Cohere, Mistral
- API key validation with test endpoints
- Atomic key rotation with health history tracking
- Bulk validation

### Model Discovery Engine
- Dynamically fetches live model lists per API key
- Normalizes model identifiers across providers and LiteLLM
- Detects context window sizes, cost estimations, capabilities (vision, streaming, tool-calling)
- Classifies models as Available / Deprecated / Preview / Enterprise Only
- Falls back to native Provider API (httpx) when LiteLLM lacks mapping for new models
- Caches results with configurable TTL

### Smart Model Router
- Multi-strategy routing (priority-based, cost-optimized, latency-optimized, random)
- Route rules with provider, model, and weight configurations
- Circuit breaker pattern with automatic recovery
- Exponential backoff retry with configurable max attempts

### Token Usage Tracking & Cost Estimation
- Real-time token counting per request
- Provider-specific cost tables for accurate estimation
- Usage breakdown by model, provider, and feature
- Cost history and trending
- Budget tracking and alerts

### Health Monitoring & Failover
- Per-key health status tracking
- Automatic failover to healthy keys/providers
- Health check endpoints with history
- Failover logs for auditing

### Security & Observability
- Prompt injection detection (common attack patterns)
- Secret redaction from traces and logs
- Full LLM request logging (observability)
- Cache layer metrics (hit/miss/eviction rates)

---

## Repository Intelligence Engine

The Repository Intelligence Engine analyzes repositories deterministically before any LLM invocation. It runs **zero LLM tokens** during analysis and provides comprehensive repository understanding to the review pipeline.

### Architecture

```
Repository
    │
    ▼
┌─────────────────┐
│   RepoWalker    │  Single-pass filesystem traversal (cached)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Intelligence    │  17 detectors running in parallel
│ Engine          │  Each with independent error handling
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Code Graph      │  7 graph builders running in parallel
│ Indexing        │  Import, Call, Module, API, DB, Config, Test
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Context         │  RAG-based retrieval with token budgeting
│ Retrieval       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ LLM             │  Only receives compressed, ranked context
│ Orchestrator    │
└─────────────────┘
```

### Intelligence Detectors

| Detector | Purpose | Zero-LLM |
|----------|---------|----------|
| `LanguageDetector` | Detects programming languages by file extension | Yes |
| `FrameworkDetector` | Detects frameworks from config files and content | Yes |
| `ArchitectureDetector` | Detects DDD, Clean, Hexagonal, MVC, Microservices, Monorepo | Yes |
| `DatabaseDetector` | Detects databases and ORMs | Yes |
| `DependencyAnalyzer` | Detects package managers | Yes |
| `TestingDetector` | Detects test frameworks and counts test files | Yes |
| `BuildDetector` | Detects build tools and Docker presence | Yes |
| `CICDDetector` | Detects CI/CD providers (GitHub Actions, GitLab CI, etc.) | Yes |
| `SecurityDetector` | Detects auth patterns, CORS, rate limiting | Yes |
| `CloudDetector` | Detects cloud providers (AWS, GCP, Azure, etc.) | Yes |
| `QueueDetector` | Detects message queues and caching solutions | Yes |
| `SecretDetector` | Detects hardcoded credentials and API keys | Yes |
| `ComplexityAnalyzer` | Analyzes cyclomatic complexity | Yes |
| `DeadCodeDetector` | Detects potentially unused code | Yes |
| `DuplicateDetector` | Detects copy-paste code blocks | Yes |
| `HealthEngine` | Calculates repository health score | Yes |
| `MetricsEngine` | Collects repository metrics | Yes |

### Adding a New Detector

To add a new detector, implement the `BaseDetector` interface:

```python
from app.intelligence.base_detector import BaseDetector, DetectorResult

class MyDetector(BaseDetector):
    @property
    def name(self) -> str:
        return "my_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        # Your detection logic here
        return DetectorResult(
            success=True,
            data={"findings": [...]},
            confidence=0.8,
        )
```

Register the detector in `intelligence/engine.py`:

```python
from app.intelligence.my_detector import MyDetector

class IntelligenceEngine:
    def __init__(self):
        self._detectors = [
            # ... existing detectors ...
            MyDetector(),  # Add your detector
        ]
```

### Code Graph Types

| Graph | Purpose | Nodes | Edges |
|-------|---------|-------|-------|
| Import Graph | Import/dependency relationships | Files/Modules | imports |
| Call Graph | Function call relationships | Functions | calls |
| Module Graph | Directory/module hierarchy | Directories | contains |
| API Graph | API endpoint definitions | Endpoints | handlers |
| DB Graph | Database model relationships | Tables/Models | references |
| Config Graph | Configuration file relationships | Configs | declares |
| Test Graph | Test-to-source mapping | Tests | tests |

---

## Supported LLM Providers

<table>
<tr>
<td align="center"><img src="https://img.shields.io/badge/Google%20Gemini-4285f4?style=for-the-badge&logo=google&logoColor=white" /><br/><sub>Available</sub></td>
<td align="center"><img src="https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white" /><br/><sub>In Development</sub></td>
<td align="center"><img src="https://img.shields.io/badge/Anthropic%20Claude-D97757?style=for-the-badge" /><br/><sub>In Development</sub></td>
<td align="center"><img src="https://img.shields.io/badge/Groq-6366f1?style=for-the-badge" /><br/><sub>In Development</sub></td>
<td align="center"><img src="https://img.shields.io/badge/DeepSeek-0066ff?style=for-the-badge" /><br/><sub>In Development</sub></td>
</tr>
<tr>
<td align="center"><img src="https://img.shields.io/badge/xAI%20Grok-000000?style=for-the-badge&logo=x&logoColor=white" /><br/><sub>In Development</sub></td>
<td align="center"><img src="https://img.shields.io/badge/OpenRouter-8B5CF6?style=for-the-badge" /><br/><sub>In Development</sub></td>
<td align="center"><img src="https://img.shields.io/badge/Azure%20OpenAI-0078D4?style=for-the-badge&logo=microsoft-azure&logoColor=white" /><br/><sub>In Development</sub></td>
<td align="center"><img src="https://img.shields.io/badge/Ollama-000000?style=for-the-badge&logo=ollama&logoColor=white" /><br/><sub>In Development</sub></td>
<td align="center"><img src="https://img.shields.io/badge/Cohere-3955ff?style=for-the-badge" /><br/><sub>In Development</sub></td>
</tr>
<tr>
<td align="center"><img src="https://img.shields.io/badge/Mistral-FF6600?style=for-the-badge" /><br/><sub>In Development</sub></td>
</tr>
</table>

> Currently **Google Gemini** is fully integrated and available. Support for OpenAI, Anthropic Claude, Groq, DeepSeek, Grok, OpenRouter, Azure OpenAI, Ollama, Cohere, and Mistral is actively being developed via the BYOK LLM Orchestrator.

---

## Context Engineering Modules

<table>
<tr>
<td align="center" width="25%">

**Repository Intelligence**
<br/><sub>17 detectors analyzing languages, frameworks, architecture pattern, database, package manager, testing, build tools, CI/CD, security auth, cloud provider, caching, queues, secrets, complexity, dead code, duplicates, repo health — all without LLM</sub>

</td>
<td align="center" width="25%">

**Code Graph Indexing**
<br/><sub>7 graph types: import graph, call graph, module graph, API endpoint graph, database model graph, configuration graph, test graph — built via regex-based code parsing</sub>

</td>
<td align="center" width="25%">

**Context Retrieval**
<br/><sub>13 specialized retrievers, 6-factor ranking engine, 5-stage compression pipeline, configurable token budgets (4K–128K), multi-layer cache, 5-stage fallback chain, graph traversal (BFS/DFS/k-hop/shortest path)</sub>

</td>
<td align="center" width="25%">

**Verification Engine**
<br/><sub>Every AI finding verified: file exists in repo, line number valid, not duplicate, not hallucinated, confidence-scored above threshold</sub>

</td>
</tr>
</table>

---

## Technology Stack

<table>
<tr>
<td><strong>Frontend</strong></td>
<td>

![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js)
![React](https://img.shields.io/badge/React-19-61dafb?style=flat-square&logo=react)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178c6?style=flat-square&logo=typescript)
![Tailwind CSS](https://img.shields.io/badge/Tailwind-4-06b6d4?style=flat-square&logo=tailwindcss)
![Zustand](https://img.shields.io/badge/Zustand-5-443e38?style=flat-square)

</td>
</tr>
<tr>
<td><strong>Backend</strong></td>
<td>

![Python](https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2-d71f00?style=flat-square)
![LangGraph](https://img.shields.io/badge/LangGraph-0-000000?style=flat-square)
![LiteLLM](https://img.shields.io/badge/LiteLLM-1-000000?style=flat-square)

</td>
</tr>
<tr>
<td><strong>Infrastructure</strong></td>
<td>

![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169e1?style=flat-square&logo=postgresql)
![In-Memory Cache](https://img.shields.io/badge/Cache-In--Memory%20LRU-FF6B6B?style=flat-square)
![Redis (Optional)](https://img.shields.io/badge/Redis-Optional-dc382d?style=flat-square&logo=redis)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ed?style=flat-square&logo=docker)

</td>
</tr>
</table>

---

## Folder Structure

```
revora/
├── backend/
│   ├── app/
│   │   ├── ai/                    # LLM service, LangGraph agents, prompts, state
│   │   ├── api/v1/endpoints/      # FastAPI routes (17 endpoint modules)
│   │   ├── cache/                 # Multi-layer caching (memory LRU + optional Redis)
│   │   │   ├── base_cache.py      # Abstract cache interface
│   │   │   ├── memory_cache.py    # LRU in-process cache (5K entries)
│   │   │   ├── redis_cache.py     # Redis-backed distributed cache (optional)
│   │   │   ├── graph_cache.py     # Graph traversal result cache
│   │   │   ├── retrieval_cache.py # Retrieval result cache
│   │   │   └── metrics.py         # Cache hit/miss/eviction tracking
│   │   ├── core/                  # Auth (JWT, bcrypt), config, security (Fernet), constants
│   │   ├── db/                    # SQLAlchemy async engine and session
│   │   ├── github/                # GitHub App auth, API client, webhook handler
│   │   ├── github_review/         # GitHub PR review format generator
│   │   ├── indexing/              # Code graph builders (7 graph types)
│   │   ├── intelligence/          # Repository Intelligence Engine (17 detectors, zero-LLM)
│   │   ├── knowledge/             # Knowledge base with DB persistence
│   │   ├── models/                # SQLAlchemy ORM models (25+ tables)
│   │   ├── orchestrator/          # Multi-provider LLM with fallbacks, retries, cost tracking
│   │   ├── pipeline/              # Review pipeline with per-stage error handling
│   │   ├── prompt_engine/         # Modular prompt builder with versioning, templates
│   │   ├── retrieval/             # Context Retrieval Engine (13 retrievers, 6-rankers, 5-compressors)
│   │   ├── schemas/               # Pydantic request/response schemas
│   │   ├── security/              # Secret redaction, prompt injection detection
│   │   ├── services/              # Business logic services
│   │   │   ├── api_key_service.py   # API key CRUD, health, rotation
│   │   │   ├── model_discovery.py   # Dynamic model discovery per provider
│   │   │   ├── provider_registry.py # Provider CRUD with encrypted storage
│   │   │   ├── model_router.py      # Smart LLM routing (priority/cost/latency)
│   │   │   ├── token_manager.py     # Token counting & usage tracking
│   │   │   ├── usage_tracker.py     # LLM request logging & analytics
│   │   │   ├── health_monitor.py    # Provider health monitoring
│   │   │   ├── cost_estimator.py    # Cost estimation & budget tracking
│   │   │   ├── retry_failover.py    # Retry with circuit breaker & failover
│   │   │   └── user_service.py      # User management
│   │   ├── sse/                   # Server-Sent Events emitter
│   │   └── verification/          # AI finding verification engine
│   ├── alembic/                   # Database migrations (9 migrations, 25+ tables)
│   ├── tests/                     # Test suite (11 test files)
│   ├── .env.example               # Environment variable template
│   └── requirements.txt
│
├── frontend/
│   ├── .env.example               # Frontend environment template
│   └── src/
│       ├── app/                   # Next.js App Router (10 pages)
│       │   └── (dashboard)/
│       │       ├── dashboard/       # Stats, recent reviews
│       │       ├── repositories/    # Repo list, model config modal
│       │       ├── reviews/         # Review list with status filters
│       │       ├── reviews/[id]/    # Review detail with markdown
│       │       └── settings/
│       │           ├── api-keys/    # API key CRUD with test/rotate/health
│       │           ├── providers/   # LLM provider management
│       │           ├── usage/       # Usage analytics dashboard
│       │           ├── health/      # Health monitoring
│       │           ├── routing/     # LLM routing configuration
│       │           └── analytics/   # Platform analytics
│       ├── components/
│       │   ├── layout/            # Sidebar, ThemeProvider
│       │   ├── shared/            # StatusBadge, Skeleton, EmptyState
│       │   └── ui/                # shadcn/ui primitives, Button, ThemeToggle
│       ├── lib/                   # Axios API client, utilities
│       ├── proxy.ts               # API proxy configuration
│       └── store/                 # Zustand stores (auth, theme)
│
├── docs/                        # Documentation
│   ├── byok-orchestrator-plan.md # BYOK LLM Orchestrator plan
│   ├── context-retrieval.md      # Context Retrieval Engine overview
│   ├── token-budget.md           # Token budget configuration guide
│   ├── ranking.md                # Ranking engine documentation
│   ├── compression.md            # Compression strategies guide
│   └── cache-strategy.md         # Caching layer documentation
├── docker-compose.yml            # PostgreSQL, Backend, Frontend
├── run.bat                       # Windows startup script
└── README.md
```

---

## Quick Start

### Docker (Recommended)

```bash
git clone https://github.com/d-kavinraja/revora.git
cd revora
docker-compose up -d
```

### Manual Setup

<details>
<summary><strong>Backend Setup</strong></summary>

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
set PYTHONPATH=.
alembic upgrade head
uvicorn app.main:app --reload
```

</details>

<details>
<summary><strong>Frontend Setup</strong></summary>

```bash
cd frontend
npm install
npm run dev
```

</details>

---

## Local Development Guide

This guide walks you through setting up Revora on your local machine from scratch.

### Prerequisites

- **Python 3.11+** — [Download](https://python.org)
- **Node.js 18+** — [Download](https://nodejs.org)
- **PostgreSQL 15+** — [Download](https://postgresql.org) or use Docker
- **Docker & Docker Compose** (optional) — [Download](https://docker.com)
- **Git** — [Download](https://git-scm.com)

### Step-by-Step Setup

#### 1. Clone the Repository

```bash
git clone https://github.com/d-kavinraja/revora.git
cd revora
```

#### 2. Start Database Services (Docker)

```bash
# Start PostgreSQL (Redis is optional)
docker run -d --name revora-postgres -p 5432:5432 -e POSTGRES_USER=revora -e POSTGRES_PASSWORD=revora_pass -e POSTGRES_DB=revora_db postgres:15-alpine
```

Or use the full Docker Compose setup:

```bash
docker-compose up -d db
```

#### 3. Configure Environment Variables

```bash
cd backend
copy .env.example .env  # Windows
# or
cp .env.example .env    # Linux/Mac
```

Edit `.env` with your values (see [Environment Variables](#environment-variables) section).

#### 4. Run Database Migrations

```bash
cd backend
set PYTHONPATH=.  # Windows
export PYTHONPATH=.  # Linux/Mac

# Activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt

# Run migrations
alembic upgrade head
```

#### 5. Start Backend Server

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The backend API will be available at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

#### 6. Start Frontend Server

```bash
cd frontend
npm install
npm run dev
```

The frontend will be available at `http://localhost:3000`.

#### 7. Verify Application

1. Open `http://localhost:3000` in your browser
2. Click "Sign in with GitHub"
3. Complete GitHub OAuth flow
4. You should see the dashboard

#### 8. Connect GitHub

1. Go to GitHub Settings > Developer settings > GitHub Apps
2. Create a new GitHub App (see [GitHub App Setup](#github-app-setup))
3. Install the app on your repositories
4. Return to Revora and click "Sync Repositories"

#### 9. Trigger First Review

1. Open a Pull Request in a connected repository
2. Revora will automatically receive the webhook
3. The AI review will appear on the PR within minutes

---

## Environment Variables

### Backend Variables

| Variable | Purpose | Required | Example | Service |
|----------|---------|----------|---------|---------|
| `APP_NAME` | Application name | No | `Revora` | Backend |
| `APP_ENV` | Environment mode | No | `development` | Backend |
| `SECRET_KEY` | Application secret key | **Yes** | `your-secret-key-here` | Backend |
| `JWT_SECRET_KEY` | JWT signing key | **Yes** | `your-jwt-secret-here` | Backend |
| `ENCRYPTION_KEY` | Fernet encryption key (32 bytes, base64) | **Yes** | `CRc9n8lOWfBsfvG-yzQ0uLodwNTjRx3UUS2a5b6zZXQ=` | Backend |
| `DATABASE_URL` | PostgreSQL connection string | **Yes** | `postgresql+asyncpg://revora:revora_pass@localhost:5432/revora_db` | Backend |
| `REDIS_URL` | Redis connection string (optional, falls back to in-memory cache) | No | `redis://localhost:6379/0` | Backend |
| `CORS_ORIGINS` | Allowed CORS origins | No | `["http://localhost:3000"]` | Backend |

### GitHub OAuth Variables

| Variable | Purpose | Required | Example | Service |
|----------|---------|----------|---------|---------|
| `GITHUB_CLIENT_ID` | GitHub OAuth App Client ID | **Yes** | `Iv23lix4UrdcNq2hoWol` | Backend + Frontend |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth App Client Secret | **Yes** | `your-client-secret` | Backend |

### GitHub App Variables

| Variable | Purpose | Required | Example | Service |
|----------|---------|----------|---------|---------|
| `GITHUB_APP_ID` | GitHub App ID | **Yes** | `4265854` | Backend |
| `GITHUB_APP_PRIVATE_KEY` | GitHub App private key (PEM format) | **Yes** | `-----BEGIN RSA PRIVATE KEY-----\n...` | Backend |
| `GITHUB_WEBHOOK_SECRET` | Webhook signature verification secret | **Yes** | `your-webhook-secret` | Backend |

### LLM API Keys

| Variable | Purpose | Required | Example | Service |
|----------|---------|----------|---------|---------|
| `GEMINI_API_KEY` | Google Gemini API key | Conditional* | `your-gemini-api-key` | Backend |
| `OPENAI_API_KEY` | OpenAI API key | Conditional* | `sk-...` | Backend |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key | Conditional* | `sk-ant-...` | Backend |
| `GROQ_API_KEY` | Groq API key | Conditional* | `gsk_...` | Backend |
| `DEEPSEEK_API_KEY` | DeepSeek API key | Conditional* | `sk-...` | Backend |
| `GROK_API_KEY` | xAI Grok API key | Conditional* | `xai-...` | Backend |

*At least one LLM provider API key is required for AI reviews. Users can also bring their own keys via the API Keys settings page, supporting **11 providers**: Gemini, OpenAI, Anthropic, Groq, DeepSeek, Grok, OpenRouter, Azure OpenAI, Ollama, Cohere, Mistral.

### Frontend Variables

| Variable | Purpose | Required | Example | Service |
|----------|---------|----------|---------|---------|
| `NEXT_PUBLIC_API_URL` | Backend API base URL | **Yes** | `http://localhost:8000/api/v1` | Frontend |
| `NEXT_PUBLIC_GITHUB_CLIENT_ID` | GitHub OAuth Client ID (for login button) | **Yes** | `Iv23lix4UrdcNq2hoWol` | Frontend |

### Security Notes

> **Never commit `.env` files or PEM keys to version control.**

- Generate a strong `SECRET_KEY` and `JWT_SECRET_KEY` (use `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- Generate `ENCRYPTION_KEY` with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- Use different secrets for development and production
- Rotate secrets regularly in production

---

## GitHub OAuth Setup

This section explains how to create a GitHub OAuth App for user authentication.

### Creating a GitHub OAuth App

1. Go to [GitHub Developer Settings](https://github.com/settings/developers)
2. Click **OAuth Apps** in the left sidebar
3. Click **New OAuth App**
4. Fill in the form:
   - **Application name**: `Revora Development`
   - **Homepage URL**: `http://localhost:3000`
   - **Authorization callback URL**: `http://localhost:3000/auth/callback`
5. Click **Register application**
6. Copy the **Client ID**
7. Click **Generate a new client secret**
8. Copy the **Client Secret** (shown only once)

### Configuring Environment Variables

Add to your `backend/.env`:

```env
GITHUB_CLIENT_ID=your_client_id_here
GITHUB_CLIENT_SECRET=your_client_secret_here
```

Add to your `frontend/.env.local` (or set in Next.js config):

```env
NEXT_PUBLIC_GITHUB_CLIENT_ID=your_client_id_here
```

### OAuth Login Flow

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant G as GitHub
    participant B as Backend

    U->>F: Click "Sign in with GitHub"
    F->>G: Redirect to GitHub OAuth
    G->>U: User authorizes app
    G->>F: Redirect with code
    F->>B: POST /api/v1/auth/github {code}
    B->>G: Exchange code for access token
    G->>B: Return access token
    B->>G: Fetch user profile
    G->>B: Return user data
    B->>B: Create/update user in DB
    B->>F: Return JWT token + user data
    F->>F: Store token in localStorage
    F->>U: Redirect to dashboard
```

### Common Mistakes

- **Callback URL mismatch**: The callback URL must exactly match what's configured in GitHub (including `http://` vs `https://`)
- **Missing scopes**: Ensure `read:user` and `user:email` scopes are requested
- **Client Secret exposed**: Never expose the client secret in frontend code

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "Invalid redirect URI" | Verify callback URL matches GitHub settings exactly |
| "Bad credentials" | Regenerate client secret in GitHub settings |
| "Email not found" | Ensure user has a public email on GitHub or grant `user:email` scope |

---

## GitHub App Setup

This section explains how to create a GitHub App for repository access and webhook handling.

### Creating a GitHub App

1. Go to [GitHub Developer Settings](https://github.com/settings/developers)
2. Click **GitHub Apps** in the left sidebar
3. Click **New GitHub App**
4. Fill in the form:

   - **GitHub App name**: `Revora AI Review`
   - **Homepage URL**: `http://localhost:3000`
   - **Webhook URL**: `http://your-public-url/api/v1/webhooks/github`
   - **Webhook secret**: Generate a strong secret (use `python -c "import secrets; print(secrets.token_urlsafe(32))"`)

5. Set permissions (see [GitHub Permissions](#github-permissions))
6. Set event subscriptions:
   - Pull requests
   - Installation
   - Installation repositories
7. Click **Create GitHub App**
8. On the app settings page:
   - Note the **App ID**
   - Click **Generate a private key**
   - Download the `.pem` file
9. Click **Install App** to install on your account/organization
10. Note the **Installation ID** from the URL after installation

### Configuring Environment Variables

Add to your `backend/.env`:

```env
GITHUB_APP_ID=your_app_id_here
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nYOUR_KEY_HERE\n-----END RSA PRIVATE KEY-----"
GITHUB_WEBHOOK_SECRET=your_webhook_secret_here
```

### Where Each Value Goes

| Value | Location | Description |
|-------|----------|-------------|
| App ID | `GITHUB_APP_ID` | Numeric ID from GitHub App settings |
| Client ID | `GITHUB_CLIENT_ID` | From OAuth App (for user login) |
| Client Secret | `GITHUB_CLIENT_SECRET` | From OAuth App (for user login) |
| Private Key | `GITHUB_APP_PRIVATE_KEY` | PEM file contents (for API access) |
| Webhook Secret | `GITHUB_WEBHOOK_SECRET` | Secret you defined in webhook settings |
| Installation ID | Stored in database | Obtained after installing the app |

### Installation Process

1. After creating the GitHub App, click **Install App**
2. Choose your personal account or organization
3. Select repositories to grant access to
4. Click **Install**
5. The Installation ID is in the URL: `https://github.com/settings/installations/{INSTALLATION_ID}`
6. Revora automatically captures this via the `installation.created` webhook

### Local Testing

For local development, use a tunneling service:

**ngrok:**
```bash
ngrok http 8000
# Use the HTTPS URL as your webhook URL
```

**Cloudflare Tunnel:**
```bash
cloudflared tunnel --url http://localhost:8000
```

---

## GitHub Permissions

The GitHub App requires the following permissions:

### Repository Permissions

| Permission | Access | Why It's Needed |
|------------|--------|-----------------|
| **Contents** | Read | Fetch repository files for context analysis |
| **Pull Requests** | Read & Write | Read PR diffs, post review comments |
| **Metadata** | Read | Access repository metadata |
| **Checks** | Read & Write | Create check runs for review status |
| **Commit Status** | Read & Write | Set commit status based on review |
| **Issues** | Read | Read issues for context |
| **Actions** | Read | Understand CI/CD workflows |
| **Administration** | Read | Access repository settings for context |

### Organization Permissions

| Permission | Access | Why It's Needed |
|------------|--------|-----------------|
| **Members** | Read | Identify team members |
| **Repositories** | Read | List organization repositories |

### Event Subscriptions

| Event | Why It's Needed |
|-------|-----------------|
| **pull_request** | Trigger reviews on PR open/reopen/sync |
| **installation** | Track app installations |
| **installation_repositories** | Track repository access changes |

---

## Webhook Configuration

### Setting Up Webhooks

1. In your GitHub App settings, go to **Webhooks**
2. Set **Payload URL**: `https://your-public-url/api/v1/webhooks/github`
3. Set **Content type**: `application/json`
4. Set **Secret**: Same as `GITHUB_WEBHOOK_SECRET` in your `.env`
5. Select events: **Pull requests**, **Installation**, **Installation repositories**

### Localhost Testing

For local development, you need a public URL to receive webhooks:

**Using ngrok:**
```bash
ngrok http 8000
# Copy the https://xxxx.ngrok.io URL
# Set as webhook URL: https://xxxx.ngrok.io/api/v1/webhooks/github
```

**Using Cloudflare Tunnel:**
```bash
cloudflared tunnel --url http://localhost:8000
# Copy the https://xxxx.trycloudflare.com URL
```

### Signature Verification

Revora verifies webhook signatures using HMAC-SHA256:

```python
# In backend/app/github/webhooks.py
expected = "sha256=" + hmac.new(
    secret.encode(),
    payload,
    hashlib.sha256,
).hexdigest()
return hmac.compare_digest(expected, signature)
```

### Webhook Events Handled

| Event | Action | Handler |
|-------|--------|---------|
| `pull_request` | `opened` | Triggers AI review pipeline |
| `pull_request` | `reopened` | Triggers AI review pipeline |
| `pull_request` | `synchronize` | Triggers AI review pipeline |
| `installation` | `created` | Links installation to user |
| `installation` | `deleted` | Removes installation and repos |
| `installation_repositories` | `added` | Adds repositories to database |
| `installation_repositories` | `removed` | Removes repositories from database |

---

## Database Setup

### PostgreSQL Installation

**Docker (Recommended):**
```bash
docker run -d --name revora-postgres \
  -p 5432:5432 \
  -e POSTGRES_USER=revora \
  -e POSTGRES_PASSWORD=revora_pass \
  -e POSTGRES_DB=revora_db \
  -v postgres_data:/var/lib/postgresql/data \
  postgres:15-alpine
```

**Manual Installation:**
1. Download PostgreSQL 15+ from [postgresql.org](https://postgresql.org)
2. Install and start the service
3. Create database and user:
```sql
CREATE USER revora WITH PASSWORD 'revora_pass';
CREATE DATABASE revora_db OWNER revora;
```

### Running Migrations

```bash
cd backend
set PYTHONPATH=.  # Windows
export PYTHONPATH=.  # Linux/Mac

# Install Alembic if not installed
pip install alembic

# Run all migrations
alembic upgrade head

# Check current migration version
alembic current

# Rollback one migration
alembic downgrade -1
```

### Database Schema

Revora uses 25+ tables across these domains:

- **Users & Auth**: `users`, `api_keys`
- **Organizations**: `organizations`, `org_members`, `teams`, `team_members`
- **GitHub**: `installations`, `repositories`, `pull_requests`
- **Reviews**: `reviews`, `review_comments`
- **Knowledge**: `repository_knowledge`, `repository_rules`, `repository_indexes`, `repository_intelligence`
- **Analytics**: `review_events`, `review_metrics`
- **BYOK Orchestrator**: `provider_registry`, `api_key_health`, `provider_health`, `failover_logs`, `llm_token_usage`, `cost_budgets`, `llm_request_logs`

### Resetting Database

```bash
# Drop and recreate database
docker exec -it revora-postgres psql -U revora -c "DROP DATABASE revora_db;"
docker exec -it revora-postgres psql -U revora -c "CREATE DATABASE revora_db OWNER revora;"

# Run migrations again
alembic upgrade head
```

---

## Redis (Optional)

Redis is **not required** to run Revora. The platform uses an in-memory LRU cache (`MemoryCache`) with 5,000 entry capacity and 300-second default TTL as the primary caching layer. Redis serves as an **optional upgrade** for distributed caching scenarios.

### When to Use Redis

- Running multiple backend instances behind a load balancer
- Need persistent cache across restarts
- High-traffic deployments requiring distributed cache coherence

### Installing Redis (Optional)

**Docker (Recommended):**
```bash
docker run -d --name revora-redis -p 6379:6379 redis:7-alpine
```

**Manual Installation:**
1. Download Redis from [redis.io](https://redis.io)
2. Install and start the service

### Cache Architecture

The caching layer uses a **fallback chain**:
1. In-memory LRU cache (always available, 5,000 entries)
2. Redis (if configured, falls back gracefully to memory cache on failure)
3. Used by: `GraphCache`, `RetrievalCache`, retrieval engine

### Enabling Redis

1. Set `REDIS_URL` in your `.env`:
   ```env
   REDIS_URL=redis://localhost:6379/0
   ```
2. Install the optional `redis` package:
   ```bash
   pip install redis
   ```
3. Restart the backend — Redis will be auto-detected

---

## Docker Setup

### Docker Compose Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `db` | `postgres:15-alpine` | 5432 | PostgreSQL database |
| `backend` | Custom build | 8000 | FastAPI backend |
| `frontend` | Custom build | 3000 | Next.js frontend |

> **Note:** Redis and Celery workers are **not included** in the default Docker Compose setup. Redis is optional (see [Redis section](#redis-optional)), and Revora does not use Celery.

### Docker Commands

```bash
# Start all services
docker-compose up -d

# Start only database
docker-compose up -d db

# View logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend

# Stop all services
docker-compose down

# Stop and remove volumes (fresh start)
docker-compose down -v

# Rebuild after changes
docker-compose up -d --build

# Check running containers
docker-compose ps
```

### Volumes

| Volume | Purpose |
|--------|---------|
| `postgres_data` | Persistent PostgreSQL data |

> There is no Redis volume since Redis is optional and not part of the default compose setup.

### Common Issues

| Issue | Solution |
|-------|----------|
| Port already in use | Change port mapping in `docker-compose.yml` or stop conflicting service |
| Database connection failed | Ensure `db` service is healthy: `docker-compose ps` |
| Backend can't connect to DB | Check `DATABASE_URL` uses `db` as hostname (not `localhost`) |

---

## Running the Application

### Expected Startup Order

1. **PostgreSQL** — Database must be running first
2. **Backend** — FastAPI server on port 8000
3. **Frontend** — Next.js dev server on port 3000

### Health Checks

```bash
# Backend health check
curl http://localhost:8000/api/v1/health
# Expected: {"status":"healthy","service":"revora-api"}

# Database health check
docker exec -it revora-postgres pg_isready -U revora

# Optional: Redis health check (if configured)
# redis-cli ping
```

### Verifying Everything Works

1. **Backend API**: Open `http://localhost:8000/docs` — you should see the FastAPI documentation
2. **Frontend**: Open `http://localhost:3000` — you should see the Revora landing page
3. **GitHub Login**: Click "Sign in with GitHub" — should redirect to GitHub OAuth
4. **Dashboard**: After login, you should see the dashboard with stats
5. **Repositories**: Go to Repositories page — should show connected repos after sync

### Common Startup Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `ModuleNotFoundError` | PYTHONPATH not set | Run `set PYTHONPATH=.` (Windows) or `export PYTHONPATH=.` (Linux/Mac) |
| `Connection refused` | Database not running | Start PostgreSQL: `docker-compose up -d db` |
| `JWT decode error` | Invalid JWT_SECRET_KEY | Generate new key and update `.env` |
| `GitHub OAuth error` | Invalid credentials | Verify `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` |

---

## Authentication Flow

### GitHub Login

1. User clicks "Sign in with GitHub" on login page
2. Frontend redirects to GitHub OAuth authorization URL
3. User authorizes the application on GitHub
4. GitHub redirects back to `/auth/callback` with authorization code
5. Frontend sends code to backend `/api/v1/auth/github`
6. Backend exchanges code for GitHub access token
7. Backend fetches user profile from GitHub API
8. Backend creates/updates user in database
9. Backend generates JWT token
10. Frontend stores token in localStorage
11. User is redirected to dashboard

### JWT Token

- **Algorithm**: HS256
- **Expiration**: 24 hours (development)
- **Payload**: `{"exp": timestamp, "sub": "user_id"}`
- **Storage**: localStorage (client-side)

### Session Management

- Tokens are stored in localStorage via Zustand persist middleware
- Tokens are sent in `Authorization: Bearer <token>` header
- Backend validates token on each authenticated request

### GitHub App Installation

1. User installs GitHub App on their account/organization
2. GitHub sends `installation.created` webhook
3. Backend links installation to authenticated user
4. Repository access is granted based on installation permissions

---

## Review Workflow

```mermaid
flowchart TD
    A[User Opens PR] --> B[GitHub Sends Webhook]
    B --> C[Revora Verifies Signature]
    C --> D[Create Review Record]
    D --> E[Phase 1: Repository Intelligence]
    E --> F[Phase 2: Code Graph Indexing]
    F --> G[Phase 3: Knowledge Base]
    G --> H[Phase 4: Context Retrieval]
    H --> I[Phase 5: Security Sanitization]
    I --> J[Phase 6: Prompt Building]
    J --> K[Phase 7: LLM Orchestration]
    K --> L[Phase 8: Verification]
    L --> M[Phase 9: GitHub Review Generation]
    M --> N[Post Review to GitHub]
    N --> O[Update Check Run Status]
```

### Complete Lifecycle

1. **GitHub OAuth** — User authenticates with GitHub
2. **Install GitHub App** — User installs Revora on repositories
3. **Repository Sync** — Revora syncs repository metadata
4. **Open Pull Request** — Developer opens a PR
5. **Webhook Received** — GitHub sends PR event to Revora
6. **Context Engineering** — Revora analyzes the repository
7. **AI Review** — LLM generates review comments
8. **Verification** — Findings are verified against actual code
9. **GitHub Review** — Review is posted as PR comment

---

## API Documentation

### Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/auth/login` | Email/password login |
| `POST` | `/api/v1/auth/register` | Register new user |
| `POST` | `/api/v1/auth/github` | GitHub OAuth login |

### Repository Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/repositories` | List connected repositories |
| `POST` | `/api/v1/repositories/sync-all` | Sync all repositories from GitHub |
| `POST` | `/api/v1/repositories/{id}/sync` | Sync specific repository PRs |
| `GET` | `/api/v1/repositories/available-models` | Get available LLM models |
| `PATCH` | `/api/v1/repositories/{id}/config` | Update repository model config |

### Review Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/reviews` | List all reviews |
| `GET` | `/api/v1/reviews/{id}` | Get review details |

### Dashboard Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/dashboard/stats` | Get dashboard statistics |

### API Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/api-keys` | List API keys |
| `POST` | `/api/v1/api-keys` | Create API key |
| `PUT` | `/api/v1/api-keys/{id}` | Update API key |
| `DELETE` | `/api/v1/api-keys/{id}` | Delete API key |
| `POST` | `/api/v1/api-keys/{id}/test` | Test API key connection |

### Webhook Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/webhooks/github` | GitHub webhook receiver |

### Health Check

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | Health check |

### Provider & Model Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/providers` | List configured LLM providers |
| `POST` | `/api/v1/providers` | Add new LLM provider |
| `PUT` | `/api/v1/providers/{id}` | Update provider configuration |
| `DELETE` | `/api/v1/providers/{id}` | Remove provider |
| `GET` | `/api/v1/models` | List available models across providers |
| `GET` | `/api/v1/llm/routes` | Get configured LLM routing rules |
| `POST` | `/api/v1/llm/route` | Create routing rule |
| `PUT` | `/api/v1/llm/route/{id}` | Update routing rule |
| `DELETE` | `/api/v1/llm/route/{id}` | Delete routing rule |

### Analytics & Usage Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/platform-usage` | Get LLM usage statistics |
| `GET` | `/api/v1/platform-usage/breakdown` | Get usage breakdown by model/provider |
| `GET` | `/api/v1/platform-analytics` | Get platform analytics |
| `GET` | `/api/v1/cost/estimates` | Get cost estimates |
| `GET` | `/api/v1/cost/history` | Get cost history |

### API Key Endpoints (Extended)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/api-keys/{id}/rotate` | Rotate API key atomically |
| `POST` | `/api/v1/api-keys/validate-all` | Validate all user API keys |
| `GET` | `/api/v1/api-keys/{id}/health` | Get API key health history |

---

## Contributing

We welcome contributions! This section explains how to contribute to Revora.

### Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/revora.git
   cd revora
   ```
3. **Add upstream remote**:
   ```bash
   git remote add upstream https://github.com/d-kavinraja/revora.git
   ```

### Branch Naming Conventions

Use descriptive branch names with prefixes:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feature/` | New features | `feature/add-inline-comments` |
| `fix/` | Bug fixes | `fix/webhook-signature-verification` |
| `docs/` | Documentation | `docs/update-readme` |
| `refactor/` | Code refactoring | `refactor/extract-review-engine` |
| `test/` | Adding tests | `test/add-webhook-tests` |

### Commit Message Conventions

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(reviews): add inline code comments
fix(webhook): handle missing signature header
docs(readme): add environment variables section
```

### Pull Request Workflow

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** and commit:
   ```bash
   git add .
   git commit -m "feat(module): add description"
   ```

3. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

4. **Open a Pull Request** on GitHub:
   - Use a descriptive title
   - Fill in the PR template
   - Link related issues

5. **Wait for review** and address feedback

### Code Review Process

- All PRs require at least one review
- Maintainers may request changes
- Address feedback promptly
- Once approved, a maintainer will merge your PR

### Coding Standards

**Python (Backend):**
- Follow PEP 8 style guide
- Use type hints for all functions
- Keep functions focused and small
- Write docstrings for public functions
- Use async/await for database operations

**TypeScript (Frontend):**
- Follow ESLint configuration
- Use TypeScript strict mode
- Prefer functional components with hooks
- Use Zustand for state management
- Keep components focused and reusable

### Running Tests

```bash
# Backend tests
cd backend
pytest

# Frontend lint
cd frontend
npm run lint
```

### Development Guidelines

- **Keep PRs small**: Focus on one change per PR
- **Write tests**: Add tests for new features
- **Update documentation**: Keep README and docs up to date
- **Follow conventions**: Match existing code style
- **Test locally**: Ensure everything works before pushing

---

## Security

### Never Commit

- `.env` files
- PEM private keys
- API keys or secrets
- Database passwords
- JWT secrets

### Use GitHub Secrets

For CI/CD, use GitHub Secrets to store sensitive values:
1. Go to repository Settings > Secrets and variables > Actions
2. Add secrets for: `DATABASE_URL`, `JWT_SECRET_KEY`, etc.

### Generate Secure Secrets

```bash
# Generate SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Rotate Secrets

- Rotate secrets regularly in production
- Update all environments when rotating
- Document when secrets were last rotated

### Report Vulnerabilities

If you discover a security vulnerability:
1. **Do NOT** open a public issue
2. Email the maintainer directly
3. Include details about the vulnerability
4. Allow time for a fix before disclosure

---

## Troubleshooting

### OAuth Issues

| Issue | Solution |
|-------|----------|
| OAuth callback mismatch | Ensure `http://localhost:3000/auth/callback` matches GitHub OAuth settings |
| Invalid redirect URI | Check for trailing slashes or protocol mismatch |
| "Bad credentials" error | Regenerate client secret in GitHub settings |

### Database Issues

| Issue | Solution |
|-------|----------|
| Connection refused | Ensure PostgreSQL is running: `docker-compose up -d db` |
| Authentication failed | Verify `DATABASE_URL` credentials in `.env` |
| Migration failed | Check Alembic version: `alembic current` |
| Reset database | Drop and recreate: see [Database Setup](#database-setup) |

### Webhook Issues

| Issue | Solution |
|-------|----------|
| Webhook not received | Verify webhook URL is publicly accessible |
| Signature verification failed | Ensure `GITHUB_WEBHOOK_SECRET` matches GitHub App settings |
| Payload too large | Check GitHub's webhook payload size limits |

### GitHub App Issues

| Issue | Solution |
|-------|----------|
| PEM errors | Ensure private key is properly formatted with `\n` newlines |
| Installation not found | Reinstall the GitHub App |
| Token expired | Revora automatically refreshes tokens |

### Docker Issues

| Issue | Solution |
|-------|----------|
| Port already in use | Stop conflicting services or change ports in `docker-compose.yml` |
| Container won't start | Check logs: `docker-compose logs <service>` |
| Build failed | Clear Docker cache: `docker-compose build --no-cache` |

### Frontend Issues

| Issue | Solution |
|-------|----------|
| API connection failed | Verify `NEXT_PUBLIC_API_URL` in `.env.local` |
| CORS errors | Check `CORS_ORIGINS` in backend `.env` |
| Module not found | Run `npm install` in frontend directory |

---

## FAQ

### General

**Q: Why isn't GitHub login working?**
A: Verify your `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are correct. Check that the callback URL in GitHub OAuth settings matches `http://localhost:3000/auth/callback`.

**Q: Where do I get the Client ID?**
A: Go to GitHub Settings > Developer settings > OAuth Apps > Your App > General tab.

**Q: Where do I put the Private Key?**
A: In `backend/.env` as `GITHUB_APP_PRIVATE_KEY`. The entire PEM content should be on one line with `\n` for newlines.

### Setup

**Q: How do I create a GitHub App?**
A: See [GitHub App Setup](#github-app-setup) section above.

**Q: How do I reset my database?**
A: Run: `docker exec -it revora-postgres psql -U revora -c "DROP DATABASE revora_db;"` then recreate and run migrations.

**Q: Why is the webhook failing?**
A: Ensure your webhook URL is publicly accessible (use ngrok for local dev). Verify the webhook secret matches your `.env`.

### Development

**Q: Can I use SQLite instead of PostgreSQL?**
A: Yes, for development. Alembic will fall back to SQLite if PostgreSQL is unavailable. However, PostgreSQL is recommended for production.

**Q: How do I add a new LLM provider?**
A: Add the provider to `PROVIDER_MODELS` in `backend/app/api/v1/endpoints/repositories.py` and implement the provider in the orchestrator.

**Q: How do I run tests?**
A: Backend: `cd backend && pytest`. Frontend: `cd frontend && npm run lint`.

---

## Development Best Practices

### Branch Strategy

- `main` — Production-ready code
- `develop` — Integration branch (future)
- `feature/*` — Feature branches
- `fix/*` — Bug fix branches
- `docs/*` — Documentation branches

### Code Style

**Python:**
- Use Black for formatting
- Use isort for import sorting
- Follow PEP 8 guidelines
- Use type hints consistently

**TypeScript:**
- Use ESLint and Prettier
- Follow the existing code style
- Use functional components
- Keep components small and focused

### Architecture Principles

- **Separation of Concerns**: Each module has a single responsibility
- **Async First**: Use async/await for I/O operations
- **Type Safety**: Use type hints and TypeScript strictly
- **Testability**: Write testable code with clear interfaces

### Pull Requests

- Keep PRs small and focused
- Write descriptive titles and descriptions
- Link related issues
- Add screenshots for UI changes
- Ensure tests pass before requesting review

### Documentation

- Update README for new features
- Add docstrings to public functions
- Keep API documentation current
- Document environment variable changes

---

## Context Retrieval Documentation

Detailed documentation for the Context Retrieval Engine is available in the `docs/` directory:

| Document | Description |
|----------|-------------|
| [context-retrieval.md](docs/context-retrieval.md) | Architecture, flow, retriever overview, API, configuration |
| [token-budget.md](docs/token-budget.md) | Presets (4K–128K), section allocation, custom budgets |
| [ranking.md](docs/ranking.md) | 6 scorers, scoring formula, custom weights, adding scorers |
| [compression.md](docs/compression.md) | 5 strategies, pipeline, deduplication, summarization |
| [cache-strategy.md](docs/cache-strategy.md) | 5 cache layers, memory/Redis backends, metrics |

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**Built with care by [Revora-Team](https://github.com/d-kavinraja)**

<img src="https://img.shields.io/badge/Revora-Context%20Engineering%20Platform-6366f1?style=for-the-badge&logo=github&logoColor=white" />

</div>
