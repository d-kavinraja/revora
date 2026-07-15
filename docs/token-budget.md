# Token Budget Engine

The Token Budget Engine controls how many tokens are allocated to each section of the retrieval context, ensuring the final prompt fits within the LLM's context window.

## Presets

| Preset | Max Tokens | Typical Use Case |
|--------|-----------|-----------------|
| `4k` | 4,096 | Small models, quick reviews |
| `8k` | 8,192 | Gemini 1.5 Flash, GPT-4o mini |
| `16k` | 16,384 | Default — balanced quality/cost |
| `32k` | 32,768 | Large PRs, deep analysis |
| `64k` | 65,536 | GPT-4 Turbo, Claude 3 |
| `128k` | 131,072 | Gemini 1.5 Pro, full-repo context |

## Section Allocation

The default allocation divides the budget across context sections:

| Section | Default % | Purpose |
|---------|-----------|---------|
| `diff` | 20% | Changed file content |
| `related` | 35% | Related files (imports, dependencies) |
| `tests` | 10% | Related test files |
| `docs` | 5% | Documentation and READMEs |
| `rules` | 5% | Repository conventions and rules |
| `api` | 10% | API endpoint definitions |
| `db` | 5% | Database schema and migrations |
| `security` | 10% | Security-sensitive code |

## Custom Budgets

```python
from app.retrieval.token_budget_engine import TokenBudgetEngine

engine = TokenBudgetEngine()

config = engine.create_config(
    max_tokens=24000,
    presets="custom",
    allocation={
        "diff": 0.25,
        "related": 0.40,
        "tests": 0.15,
        "api": 0.10,
        "security": 0.10,
    },
)
```

## How It Works

1. The engine receives the total budget (e.g., 16,384 tokens)
2. It reserves a configurable overhead (default 10%) for prompt formatting
3. The remaining tokens are divided by section allocation percentages
4. Each section tracks its actual token usage via a conservative token counter
5. If a section exceeds its allocation, its content is compressed or truncated
6. Unused tokens from one section can be redistributed to others

## Integration

The Token Budget Engine is called at the end of the retrieval pipeline:

```
Retrievers → Ranking → Compression → Token Budget → Final Context
```

It wraps the final context in a `RetrievalResult` with:

```python
@dataclass
class RetrievalResult:
    context: str
    sources: list[ContextSource]
    tokens_used: int
    max_tokens: int
    scores: dict[str, float]
    metadata: dict
```

## Testing

```bash
cd backend
python -m pytest tests/test_token_budget.py -v
```
