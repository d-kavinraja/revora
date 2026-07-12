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

**Revora** is not another AI code review tool that reads diffs. It is a **Context Engineering Platform** that builds deep repository understanding before reasoning — understanding architecture, dependencies, conventions, and developer intent to deliver enterprise-grade reviews.

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
- Builds **code graphs** (imports, calls, modules)
- Retrieves **only relevant context** for each change
- **Verifies every finding** against actual code
- Streams the full pipeline in **real-time**

</td>
</tr>
</table>

---

## Architecture Overview

```mermaid
graph TB
    subgraph Frontend["🖥️ Frontend — Next.js 16"]
        UI[Dashboard & Review UI]
        SSE[Real-Time SSE Stream]
    end

    subgraph Backend["⚙️ Backend — FastAPI"]
        WH[Webhook Receiver]
        PIPE[Review Pipeline Orchestrator]
    end

    subgraph ContextEngine["🧠 Context Engineering Engine"]
        direction TB
        I1["📊 Repository Intelligence<br/>Languages, Frameworks, Architecture"]
        I2["🔍 Repository Indexing<br/>AST, Import Graph, Call Graph"]
        I3["📚 Knowledge Base<br/>Conventions, Rules, Summaries"]
        I4["🎯 Context Retrieval<br/>RAG, Ranking, Compression"]
        I5["📝 Prompt Builder<br/>Modular, Versioned Prompts"]
        I6["🤖 LLM Orchestrator<br/>Multi-Provider with Fallbacks"]
        I7["✅ Verification Engine<br/>File/Line/Hallucination Checks"]
        I8["📋 Review Generator<br/>GitHub API Format"]
    end

    subgraph Data["💾 Data Layer"]
        PG[(PostgreSQL)]
        RD[(Redis)]
    end

    subgraph External["🌐 External"]
        GH[GitHub API]
        LLM[LLM Providers<br/>Gemini / OpenAI / Claude / Groq / DeepSeek]
    end

    UI <--> SSE
    SSE <--> PIPE
    WH --> PIPE
    PIPE --> I1 --> I2 --> I3 --> I4 --> I5 --> I6 --> I7 --> I8
    PIPE <--> PG
    PIPE <--> RD
    I8 <--> GH
    I6 <--> LLM
    SSE <--> UI
```

---

## Review Pipeline Flow

```mermaid
sequenceDiagram
    participant GH as GitHub
    participant WH as Webhook
    participant PIPE as Pipeline
    participant INT as Intelligence
    participant IDX as Indexer
    participant RET as Retriever
    participant LLM as LLM Provider
    participant VER as Verifier
    participant GEN as Review Generator
    participant UI as Frontend (SSE)

    GH->>WH: PR Opened/Reopened
    WH->>PIPE: Trigger Review
    PIPE->>UI: SSE: Pipeline Started

    PIPE->>INT: Phase 1: Analyze Repo
    INT-->>PIPE: Languages, Frameworks, Architecture

    PIPE->>IDX: Phase 2: Build Code Graphs
    IDX-->>PIPE: Import/Call/Module/API Graphs

    PIPE->>PIPE: Phase 3: Load Knowledge Base
    PIPE->>RET: Phase 4: Retrieve Context
    RET-->>PIPE: Ranked, Compressed Context

    PIPE->>PIPE: Phase 5: Build Prompt
    PIPE->>LLM: Phase 6: Send to LLM
    LLM-->>PIPE: AI Review Response

    PIPE->>VER: Phase 7: Verify Findings
    VER-->>PIPE: Verified, Confidence-Scored

    PIPE->>GEN: Phase 8: Generate GitHub Review
    GEN-->>PIPE: PR Comment + Inline Notes

    PIPE->>GH: Publish Review
    PIPE->>UI: SSE: Review Complete
```

---

## Features

<table>
<tr>
<td align="center" width="33%">

<img src="https://img.shields.io/badge/🧠-Repository%20Intelligence-6366f1?style=for-the-badge" /><br/>

**Repository Intelligence**
<br/><sub>Languages, frameworks, architecture, database, CI/CD, security patterns — all detected without LLM</sub>

</td>
<td align="center" width="33%">

<img src="https://img.shields.io/badge/📊-Code%20Graphs-06b6d4?style=for-the-badge" /><br/>

**Code Graph Indexing**
<br/><sub>Import graphs, call graphs, module graphs, API graphs, DB models, test coverage maps</sub>

</td>
<td align="center" width="33%">

<img src="https://img.shields.io/badge/🎯-Context%20Retrieval-10b981?style=for-the-badge" /><br/>

**Smart Context Retrieval**
<br/><sub>Only relevant files retrieved. Token-budgeted, compressed, deduplicated context</sub>

</td>
</tr>
<tr>
<td align="center" width="33%">

<img src="https://img.shields.io/badge/🤖-Multi-Provider%20LLM-f59e0b?style=for-the-badge" /><br/>

**Multi-Provider LLM**
<br/><sub>Gemini, OpenAI, Claude, Groq, DeepSeek, Ollama — with fallbacks, retries, cost tracking</sub>

</td>
<td align="center" width="33%">

<img src="https://img.shields.io/badge/✅-Verification%20Engine-22c55e?style=for-the-badge" /><br/>

**Verification Engine**
<br/><sub>Every finding verified: file exists, line exists, not hallucinated, confidence-scored</sub>

</td>
<td align="center" width="33%">

<img src="https://img.shields.io/badge/📡-Real-Time%20SSE-8b5cf6?style=for-the-badge" /><br/>

**Real-Time Pipeline**
<br/><sub>Watch every stage execute live — no black boxes, full transparency and explainability</sub>

</td>
</tr>
<tr>
<td align="center" width="33%">

<img src="https://img.shields.io/badge/🔒-Security%20First-ef4444?style=for-the-badge" /><br/>

**Security & Sanitization**
<br/><sub>Secret redaction, prompt injection detection, sandboxed repo cloning</sub>

</td>
<td align="center" width="33%">

<img src="https://img.shields.io/badge/💰-BYOK%20Cost%20Control-f97316?style=for-the-badge" /><br/>

**Bring Your Own Key**
<br/><sub>Users provide their own API keys. Full cost transparency with token dashboards</sub>

</td>
<td align="center" width="33%">

<img src="https://img.shields.io/badge/🏗️-Enterprise%20Ready-6366f1?style=for-the-badge" /><br/>

**Enterprise Ready**
<br/><sub>Clean Architecture, SOLID principles, async workers, Docker deployment</sub>

</td>
</tr>
</table>

---

## Supported LLM Providers

<table>
<tr>
<td align="center"><img src="https://img.shields.io/badge/Google%20Gemini-4285f4?style=for-the-badge&logo=google&logoColor=white" /><br/><sub>Default</sub></td>
<td align="center"><img src="https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white" /><br/><sub>GPT-4o</sub></td>
<td align="center"><img src="https://img.shields.io/badge/Anthropic%20Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white" /><br/><sub>Claude Sonnet</sub></td>
<td align="center"><img src="https://img.shields.io/badge/Groq-6366f1?style=for-the-badge" /><br/><sub>Llama 3.3</sub></td>
<td align="center"><img src="https://img.shields.io/badge/DeepSeek-0066ff?style=for-the-badge" /><br/><sub>DeepSeek Chat</sub></td>
</tr>
</table>

All providers are accessed through **LiteLLM** with automatic fallbacks, retries, and rate limiting.

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
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088ff?style=flat-square&logo=githubactions)

</td>
</tr>
</table>

---

## Context Engineering Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    REVORA CONTEXT ENGINEERING FLOW                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│  │  📊 Repo  │───▶│ 🔍 Index │───▶│ 📚 Know  │───▶│ 🎯 RAG   │     │
│  │ Intelligence│  │  Graphs  │    │  Base    │    │ Retrieve │     │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘     │
│       │                │               │               │            │
│       ▼                ▼               ▼               ▼            │
│  Languages       Import Graph    Conventions     Ranked Files      │
│  Frameworks      Call Graph      Rules           Compressed        │
│  Architecture    Module Graph    Summaries       Token-Budgeted    │
│  Database        API Graph       ADRs            Deduplicated      │
│  CI/CD           DB Graph        Learnings                        │
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│  │ 📝 Prompt │───▶│ 🤖 LLM   │───▶│ ✅ Verify│───▶│ 📋 GitHub│     │
│  │  Builder  │    │Orchestr.│    │  Engine  │    │  Review  │     │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘     │
│       │                │               │               │            │
│       ▼                ▼               ▼               ▼            │
│  System Prompt    Multi-Provider  File Exists     PR Comments      │
│  Repo Context     Fallbacks       Line Exists     Risk Score       │
│  Diff Content     Retries         Not Duplicate   Suggestions      │
│  Related Files    Cost Tracking   Confidence      Summary          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Folder Structure

```
revora/
├── backend/
│   ├── app/
│   │   ├── ai/                  # Core AI pipeline (LLM, graph, prompts)
│   │   ├── api/v1/endpoints/    # FastAPI route handlers
│   │   ├── core/                # Auth, config, security, dependencies
│   │   ├── db/                  # SQLAlchemy engine & session
│   │   ├── github/              # GitHub App auth, client, webhooks
│   │   ├── intelligence/        # 🧠 Repository Intelligence Engine
│   │   ├── indexing/            # 🔍 Code Graph Indexing
│   │   ├── knowledge/           # 📚 Knowledge Base
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── orchestrator/        # 🤖 LLM Orchestrator
│   │   ├── pipeline/            # 🔗 Review Pipeline Orchestrator
│   │   ├── prompt_engine/       # 📝 Prompt Builder
│   │   ├── retrieval/           # 🎯 Context Retrieval Engine
│   │   ├── security/            # 🔒 Sanitization & injection detection
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── services/            # Business logic services
│   │   ├── sse/                 # 📡 Server-Sent Events
│   │   ├── verification/        # ✅ Finding Verification Engine
│   │   ├── github_review/       # 📋 GitHub Review Generator
│   │   └── worker/              # Celery background tasks
│   ├── alembic/                 # Database migrations
│   └── requirements.txt
│
├── frontend/
│   └── src/
│       ├── app/                 # Next.js App Router pages
│       ├── components/          # React components
│       │   ├── layout/          # Sidebar, ThemeProvider
│       │   ├── shared/          # StatusBadge, Skeleton, EmptyState
│       │   └── ui/              # shadcn/ui primitives
│       ├── lib/                 # API client, utilities
│       └── store/               # Zustand state stores
│
├── docker-compose.yml           # Full stack deployment
└── README.md
```

---

## Real-Time Execution Dashboard

Revora does not show a loading spinner. Users watch every pipeline stage execute live:

<table>
<tr>
<td align="center">

**Pipeline Timeline**
<br/><sub>30+ stages with status indicators</sub>

</td>
<td align="center">

**Live Log Stream**
<br/><sub>Real-time SSE event streaming</sub>

</td>
<td align="center>

**Token Dashboard**
<br/><sub>Input/output tokens, cost, latency</sub>

</td>
</tr>
</table>

Each stage exposes:
- ⏳ **Status** — Waiting / Running / Completed / Failed / Skipped
- ⏱️ **Duration** — Execution time per stage
- 📊 **Metrics** — Files scanned, tokens used, context size
- 📝 **Logs** — Detailed execution logs

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

We welcome contributions! Please see our contributing guidelines.

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

**Built with ❤️ by [Kavinraja.D](https://github.com/d-kavinraja)**

<img src="https://img.shields.io/badge/Revora-Context%20Engineering%20Platform-6366f1?style=for-the-badge&logo=github&logoColor=white" />

</div>
