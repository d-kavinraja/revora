import logging
from typing import Optional

from app.retrieval.models import RetrievalResult
from app.retrieval.compression.base_strategy import BaseCompressionStrategy
from app.retrieval.compression.strategies.dedup import DedupStrategy
from app.retrieval.compression.strategies.truncation import TruncationStrategy
from app.retrieval.compression.strategies.import_prune import ImportPruneStrategy
from app.retrieval.compression.strategies.symbol_merge import SymbolMergeStrategy
from app.retrieval.compression.budget_allocator import budget_allocator
from app.retrieval.token_budget_engine import token_budget_engine

logger = logging.getLogger(__name__)


class CompressionEngine:
    def __init__(self):
        self._strategies: list[BaseCompressionStrategy] = []

    def register_strategy(self, strategy: BaseCompressionStrategy) -> None:
        self._strategies.append(strategy)
        logger.info(f"Registered compression strategy: {strategy.name}")

    async def compress(
        self,
        result: RetrievalResult,
        total_budget: int,
    ) -> None:
        if not self._strategies:
            logger.warning("No compression strategies registered")
            return

        budget = budget_allocator.allocate(result, total_budget)
        all_contexts = result.all_contexts()

        dedup_strategies = [s for s in self._strategies if s.name == "dedup"]
        other_strategies = [s for s in self._strategies if s.name != "dedup"]

        compressed: list = []

        for ctx in all_contexts:
            current = ctx
            for strategy in dedup_strategies:
                deduped = await strategy.safe_compress(current, total_budget)
                if deduped is None:
                    break
                current = deduped
            else:
                compressed.append(current)

        max_tokens_per_file = max(200, total_budget // max(len(compressed), 1))

        final: list = []
        for ctx in compressed:
            current = ctx
            for strategy in other_strategies:
                result_str = await strategy.safe_compress(current, max_tokens_per_file)
                if result_str is not None:
                    current = result_str
            final.append(current)

        self._distribute_compressed(result, final)

        budget_allocator.enforce_budget(result, budget)

        logger.info(
            f"CompressionEngine: {len(compressed)} files after dedup, "
            f"{len(final)} after compression, "
            f"budget={budget.total}, used={result.total_tokens}"
        )

    def _distribute_compressed(
        self,
        result: RetrievalResult,
        compressed: list,
    ) -> None:
        result.changed_files.clear()
        result.related_files.clear()
        result.test_files.clear()
        result.config_files.clear()
        result.api_endpoints.clear()
        result.db_schemas.clear()
        result.security_context.clear()
        result.impact_context.clear()
        result.historical_context.clear()
        result.rule_context.clear()
        result.documentation_context.clear()

        for ctx in compressed:
            if ctx.source == "changed_file":
                result.changed_files.append(ctx)
            elif ctx.source in ("test_graph", "test_file"):
                result.test_files.append(ctx)
            elif ctx.source == "config":
                result.config_files.append(ctx)
            elif ctx.source == "api_endpoint":
                result.api_endpoints.append(ctx)
            elif ctx.source == "db_schema":
                result.db_schemas.append(ctx)
            elif ctx.source == "security":
                result.security_context.append(ctx)
            elif ctx.source == "impact":
                result.impact_context.append(ctx)
            elif ctx.source == "historical":
                result.historical_context.append(ctx)
            elif ctx.source == "rule":
                result.rule_context.append(ctx)
            elif ctx.source == "documentation":
                result.documentation_context.append(ctx)
            else:
                result.related_files.append(ctx)


compression_engine = CompressionEngine()
compression_engine.register_strategy(DedupStrategy())
compression_engine.register_strategy(ImportPruneStrategy())
compression_engine.register_strategy(SymbolMergeStrategy())
compression_engine.register_strategy(TruncationStrategy())
