# Compression Engine

The Compression Engine reduces the token footprint of retrieved context using configurable strategies, applied in sequence.

## Strategies

| Strategy | Order | Token Savings | Description |
|----------|-------|---------------|-------------|
| `DeduplicationStrategy` | 1 | 5–20% | Removes duplicate code blocks and overlapping context |
| `ImportPruneStrategy` | 2 | 5–15% | Strips import statements; keeps only local imports |
| `SymbolMergeStrategy` | 3 | 10–25% | Merges function/class signatures into compact signatures |
| `TruncationStrategy` | 4 | Variable | Truncates each section to fit its token budget allocation |
| `SummarizeStrategy` | 5 | 40–80% | Replaces verbose code blocks with LLM-generated summaries |

## Pipeline

```
Input Context → Dedup → Import Prune → Symbol Merge → Truncate → Summarize → Output
```

Each strategy implements:

```python
from app.retrieval.compression.base_strategy import BaseCompressionStrategy

class MyStrategy(BaseCompressionStrategy):
    @property
    def name(self) -> str:
        return "my_strategy"

    async def compress(self, context: str, budget: int) -> tuple[str, int]:
        # Return (compressed_text, tokens_saved)
        ...
```

## Configuration

```python
from app.retrieval.compression.engine import CompressionEngine

engine = CompressionEngine(
    strategies=["dedup", "import_prune", "symbol_merge", "truncation", "summarize"],
)

result = await engine.compress(
    context=raw_context,
    budget=12000,
)
```

## Deduplication

Deduplication uses MinHash fingerprinting on code blocks to identify and remove near-duplicate content without needing exact string matches.

## Summarization

Summarization is an optional strategy (requires an LLM call). When enabled, it replaces verbose sections with condensed summaries. The summarization LLM call is tracked in the retrieval metrics.

## Budget Allocator

The `BudgetAllocator` distributes token budgets across context sections before compression strategies are applied:

```python
from app.retrieval.compression.budget_allocator import BudgetAllocator

allocator = BudgetAllocator(total_budget=16000, overhead=0.10)
allocations = allocator.allocate(sections)
```

## Testing

```bash
cd backend
python -m pytest tests/test_compression_engine.py -v
```
