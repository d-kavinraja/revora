# Ranking Engine

The Ranking Engine scores retrieved context by multi-factor relevance, ensuring the most important information is prioritized before compression.

## Scorers

| Scorer | Factor | Range | Description |
|--------|--------|-------|-------------|
| `GraphDistanceScorer` | Proximity | 0.0–1.0 | Files closer to changed files in code graphs score higher |
| `FileImportanceScorer` | Centrality | 0.0–1.0 | Hubs (highly imported files) score higher |
| `DependencyWeightScorer` | Impact | 0.0–1.0 | Files with many dependents score higher |
| `ChangeFrequencyScorer` | Volatility | 0.0–1.0 | Frequently changed files score higher |
| `SecurityImpactScorer` | Security | 0.0–1.0 | Security-sensitive files (auth, crypto, data) score higher |
| `TestCoverageScorer` | Testing | 0.0–1.0 | Files with high test coverage score higher |

## Scoring Formula

```
final_score = Σ(weight_i × normalized_score_i) / Σ(weight_i)
```

Default weights:

```python
DEFAULT_WEIGHTS = {
    "graph_distance": 0.30,
    "file_importance": 0.20,
    "dependency_weight": 0.20,
    "change_frequency": 0.10,
    "security_impact": 0.10,
    "test_coverage": 0.10,
}
```

## Normalization

Each scorer produces raw scores in its own range. The normalizer maps all scores to [0.0, 1.0] using min-max scaling before final aggregation.

## Custom Weights

```python
from app.retrieval.ranking.engine import RankingEngine

engine = RankingEngine()

results = await engine.rank(
    contexts=[...],
    weights={
        "graph_distance": 0.40,
        "security_impact": 0.30,
        "file_importance": 0.30,
    },
)
```

## Adding a New Scorer

```python
from app.retrieval.ranking.base_scorer import BaseScorer

class MyScorer(BaseScorer):
    @property
    def name(self) -> str:
        return "my_scorer"

    async def score(self, context, retrieval_context) -> float:
        # Return a value in [0.0, 1.0]
        return 0.75
```

Register in `ranking/engine.py` under the `_scorers` dictionary.

## Testing

```bash
cd backend
python -m pytest tests/test_ranking_engine.py -v
```
