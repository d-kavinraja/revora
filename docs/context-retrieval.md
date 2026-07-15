# Context Retrieval Engine

The Context Retrieval Engine is the **Phase 4** component of Revora's Context Engineering pipeline. It selects, ranks, compresses, and budgets relevant context from the repository before passing it to the LLM Orchestrator.

## Architecture

```
Repository Graphs + Knowledge Base
                │
                ▼
┌─────────────────────────────────────┐
│          Retrieval Engine           │
│  ┌───────────────────────────────┐  │
│  │       Fallback Chain          │  │
│  │  ┌─────────┐                  │  │
│  │  │  Graph   │  (NetworkX)     │  │
│  │  │  Traversal├──► BFS/DFS/K-hop│  │
│  │  └────┬────┘                  │  │
│  │       ▼                       │  │
│  │  ┌─────────┐                  │  │
│  │  │  KB     │  (PostgreSQL)    │  │
│  │  │  Retriever                │  │
│  │  └────┬────┘                  │  │
│  │       ▼                       │  │
│  │  ┌─────────┐                  │  │
│  │  │ Static  │  (AST/Regex)     │  │
│  │  │ Analysis                   │  │
│  │  └────┬────┘                  │  │
│  │       ▼                       │  │
│  │  ┌─────────┐                  │  │
│  │  │  Diff   │  (Git)           │  │
│  │  │  Analysis                  │  │
│  │  └────┬────┘                  │  │
│  │       ▼                       │  │
│  │  ┌─────────┐                  │  │
│  │  │ Graceful│  (Minimal)       │  │
│  │  │ Degrade │                  │  │
│  │  └─────────┘                  │  │
│  └───────────────────────────────┘  │
│              │                      │
│              ▼                      │
│  ┌───────────────────────────────┐  │
│  │      Ranking Engine           │  │
│  │  • Graph Distance             │  │
│  │  • File Importance            │  │
│  │  • Dependency Weight          │  │
│  │  • Change Frequency           │  │
│  │  • Security Impact            │  │
│  │  • Test Coverage              │  │
│  └───────────────┬───────────────┘  │
│                  │                  │
│                  ▼                  │
│  ┌───────────────────────────────┐  │
│  │     Compression Engine        │  │
│  │  • Deduplication              │  │
│  │  • Truncation                 │  │
│  │  • Import Pruning             │  │
│  │  • Symbol Merging             │  │
│  │  • Summarization              │  │
│  └───────────────┬───────────────┘  │
│                  │                  │
│                  ▼                  │
│  ┌───────────────────────────────┐  │
│  │    Token Budget Engine        │  │
│  │  • 4K / 8K / 16K / 32K       │  │
│  │    64K / 128K Presets         │  │
│  │  • Custom Budgets             │  │
│  │  • Section Allocation         │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

## Retrieval Flow

1. **Retrieval Engine** receives a query (changed files, PR diff, or natural language intent)
2. **Fallback Chain** tries each retriever strategy in order until context is found
3. **Ranking Engine** scores and sorts retrieved context by relevance
4. **Compression Engine** deduplicates, prunes, and optionally summarizes
5. **Token Budget Engine** ensures output fits within the configured token limit
6. **Result** is returned as a `RetrievalResult` with context, metadata, and scores

## Specialized Retrievers

| Retriever | Source | Use Case |
|-----------|--------|----------|
| `ChangedFileRetriever` | Git diff | Files modified in the PR |
| `ImportRetriever` | Import graph | Files imported by changed files |
| `DependencyRetriever` | Dependency graph | Direct and transitive dependencies |
| `CallGraphRetriever` | Call graph | Functions called or calling changed code |
| `ModuleRetriever` | Module graph | Sibling modules in same directory |
| `APIRetriever` | API graph | API endpoints affected by changes |
| `DBRetriever` | DB graph | Database models and migrations |
| `SecurityRetriever` | Security graph | Security-sensitive code paths |
| `ImpactRetriever` | Cross-graph | Files with high change impact |
| `HistoricalRetriever` | Git history | Files frequently changed together |
| `DocumentationRetriever` | Knowledge base | Related docs and READMEs |
| `TestRetriever` | Test graph | Tests for changed code |
| `RuleRetriever` | Knowledge base | Convention rules for changed files |

## API

```python
from app.retrieval import retrieval_engine

result = await retrieval_engine.retrieve(
    repo_id="uuid",
    repo_path="/path/to/repo",
    changed_files=["src/app/main.py", "src/app/routes.py"],
    budget=RetrievalConfig(
        max_tokens=16000,
        presets="16k",
        allocation={
            "diff": 0.20,
            "related": 0.35,
            "tests": 0.10,
            "docs": 0.05,
            "rules": 0.05,
            "api": 0.10,
            "db": 0.05,
            "security": 0.10,
        }
    ),
)

print(result.context)        # Compressed context string
print(result.sources)        # List of source files
print(result.tokens_used)    # Token count
print(result.scores)         # Per-file relevance scores
```

## Configuration

Configuration is managed via `RetrievalConfig`:

```python
from app.retrieval.models import RetrievalConfig

config = RetrievalConfig(
    max_tokens=16000,
    presets="16k",
    allocation={...},        # Per-section token allocation
    enabled_retrievers=[...], # Subset of retrievers to use
    ranking_weights={...},   # Custom scoring weights
    compression_strategies=[...], # Compression pipeline order
    use_cache=True,
    cache_ttl=300,
)
```

## Testing

```bash
cd backend
python -m pytest tests/test_retrieval_engine.py -v
python -m pytest tests/test_fallback.py -v
python -m pytest tests/test_retrievers.py -v
```
