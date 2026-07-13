<div align="center">

<img src="https://img.shields.io/badge/Revora-AI%20Code%20Review-6366f1?style=for-the-badge&logo=github&logoColor=white" alt="Revora Banner" />

# **Revora**

### The Open-Source Context Engineering Platform for AI Code Reviews

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

**Revora** is not another AI code review tool that reads diffs. It is a **Context Engineering Platform** that builds deep repository understanding before reasoning — analyzing architecture, dependencies, conventions, and developer intent to deliver enterprise-grade reviews.

</div>

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
        RD[(Redis 7)]
    end

    subgraph External["External Services"]
        GH[GitHub API - Webhooks, PR Reviews, Check Runs]
        LLM[Gemini / OpenAI / Claude / Groq / DeepSeek]
    end

    UI <--> API
    ConfigModal --> API
    WH --> I1
    I1 --> I2 --> I3 --> I4 --> I5 --> I6 --> I7 --> I8
    SEC --> I4
    INJ --> I4
    API <--> PG
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
- Repository Intelligence Engine (13 detectors)
- Repository Indexing (7 code graphs)
- Knowledge Base with PostgreSQL persistence
- Context Retrieval with RAG and token budgeting
- Modular Prompt Builder
- Multi-Provider LLM Orchestrator (Gemini, OpenAI, Claude, Groq, DeepSeek)
- Verification Engine (file/line checks, hallucination detection)
- GitHub Review Generator (inline comments, risk scoring)
- Security layer (secret redaction, prompt injection detection)
- SSE real-time event emitter
- Repository-level model configuration

**Backend - Core:**
- GitHub App authentication (JWT + installation tokens)
- GitHub OAuth login flow
- Webhook receiver with HMAC verification
- Review pipeline with 8-phase execution
- Celery worker configuration
- Alembic migrations (4 migrations, 17 tables)

**Frontend:**
- Landing page with hero and features
- GitHub OAuth login
- Dashboard with stats and recent reviews
- Repositories page with model configuration modal
- Reviews list with status filters
- Review detail with markdown rendering
- Settings page (API keys management)
- Light/dark mode toggle
- Responsive sidebar with collapse
- Shared components (StatusBadge, Skeleton, EmptyState)

</td>
<td width="50%" valign="top">

### In Development

**AI Capabilities:**
- Multi-provider LLM support (only Gemini available now)
- Auto-remediation (generating fix commits)
- Conversational PR interface (Chat with PR)
- PR description auto-generation

**GitHub Integration:**
- GitHub Checks API (pass/fail status checks)
- Inline code annotations on PR diffs

**Context Engineering:**
- Cross-repository context (microservices)
- Historical PR context understanding
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
- API keys settings page (route exists, needs full UI)

</td>
</tr>
</table>

---

## Supported LLM Providers

<table>
<tr>
<td align="center"><img src="https://img.shields.io/badge/Google%20Gemini-4285f4?style=for-the-badge&logo=google&logoColor=white" /><br/><sub>Available</sub></td>
<td align="center"><img src="https://img.shields.io/badge/OpenAI-Coming%20Soon-412991?style=for-the-badge&logo=openai&logoColor=white" /><br/><sub>In Development</sub></td>
<td align="center"><img src="https://img.shields.io/badge/Anthropic%20Claude-Coming%20Soon-D97757?style=for-the-badge" /><br/><sub>In Development</sub></td>
<td align="center"><img src="https://img.shields.io/badge/Groq-Coming%20Soon-6366f1?style=for-the-badge" /><br/><sub>In Development</sub></td>
<td align="center"><img src="https://img.shields.io/badge/DeepSeek-Coming%20Soon-0066ff?style=for-the-badge" /><br/><sub>In Development</sub></td>
</tr>
</table>

> Currently only **Google Gemini** is fully integrated. Multi-provider support is actively being developed.

---

## Context Engineering Modules

<table>
<tr>
<td align="center" width="25%">

**Repository Intelligence**
<br/><sub>13 detectors analyzing languages, frameworks, architecture pattern, database, package manager, testing, build tools, CI/CD, security auth, cloud provider, caching, queues, repo type — all without LLM</sub>

</td>
<td align="center" width="25%">

**Code Graph Indexing**
<br/><sub>7 graph types: import graph, call graph, module graph, API endpoint graph, database model graph, configuration graph, test graph — built via regex-based code parsing</sub>

</td>
<td align="center" width="25%">

**Context Retrieval**
<br/><sub>RAG-based retrieval from code graphs, hybrid ranking, context compression, token budgeting (5k-12k per review), deduplication</sub>

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
![Redis](https://img.shields.io/badge/Redis-7-dc382d?style=flat-square&logo=redis)
![Celery](https://img.shields.io/badge/Celery-5-9ddc10?style=flat-square)
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
│   │   ├── api/v1/endpoints/      # FastAPI routes (auth, repos, reviews, dashboard, webhooks)
│   │   ├── core/                  # Auth (JWT, bcrypt), config, security (Fernet encryption)
│   │   ├── db/                    # SQLAlchemy async engine and session
│   │   ├── github/                # GitHub App auth, API client, webhook handler
│   │   ├── github_review/         # GitHub PR review format generator
│   │   ├── indexing/              # Code graph builders (import, call, module, API, DB, config, test)
│   │   ├── intelligence/          # Repository analysis (13 detectors, no LLM)
│   │   ├── knowledge/             # Knowledge base with DB persistence and caching
│   │   ├── models/                # SQLAlchemy ORM models (17 tables)
│   │   ├── orchestrator/          # Multi-provider LLM with fallbacks and cost tracking
│   │   ├── pipeline/              # 8-phase review pipeline orchestrator
│   │   ├── prompt_engine/         # Modular prompt builder with templates
│   │   ├── retrieval/             # RAG context retrieval with ranking and compression
│   │   ├── schemas/               # Pydantic request/response schemas
│   │   ├── security/              # Secret redaction, prompt injection detection
│   │   ├── services/              # Business logic (user, API key management)
│   │   ├── sse/                   # Server-Sent Events emitter
│   │   ├── verification/          # AI finding verification engine
│   │   └── worker/                # Celery background tasks
│   ├── alembic/                   # Database migrations (4 migrations)
│   └── requirements.txt
│
├── frontend/
│   └── src/
│       ├── app/                   # Next.js App Router (9 pages)
│       ├── components/            # React components
│       │   ├── layout/            # Sidebar, ThemeProvider
│       │   ├── shared/            # StatusBadge, Skeleton, EmptyState
│       │   └── ui/                # shadcn/ui primitives, Button, LoaderIcon, ThemeToggle
│       ├── lib/                   # Axios API client, utilities
│       └── store/                 # Zustand stores (auth, theme)
│
├── docker-compose.yml
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

## Contributing

We welcome contributions! Check the [Issues](https://github.com/d-kavinraja/revora/issues) tab for open tasks.

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**Built with care by [Kavinraja.D](https://github.com/d-kavinraja)**

<img src="https://img.shields.io/badge/Revora-Context%20Engineering%20Platform-6366f1?style=for-the-badge&logo=github&logoColor=white" />

</div>
