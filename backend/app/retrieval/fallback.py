import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RetrievalFallback:
    STRATEGIES = [
        "graph_retrieval",
        "knowledge_base",
        "static_analysis",
        "pr_diff_only",
        "graceful_failure",
    ]

    def __init__(self):
        self._current_strategy_index = 0
        self._used_strategies: list[str] = []

    @property
    def current_strategy(self) -> str:
        return self.STRATEGIES[self._current_strategy_index]

    @property
    def used_strategies(self) -> list[str]:
        return list(self._used_strategies)

    @property
    def has_fallback(self) -> bool:
        return self._current_strategy_index < len(self.STRATEGIES) - 1

    def escalate(self) -> str:
        if self.has_fallback:
            self._current_strategy_index += 1
            strategy = self.STRATEGIES[self._current_strategy_index]
            self._used_strategies.append(strategy)
            logger.info(f"Fallback escalated to: {strategy}")
            return strategy
        return "graceful_failure"

    def reset(self) -> None:
        self._current_strategy_index = 0
        self._used_strategies = []
        logger.debug("Fallback chain reset")

    def should_use_graph(self) -> bool:
        return self.current_strategy == "graph_retrieval"

    def should_use_knowledge_base(self) -> bool:
        return self.current_strategy == "knowledge_base"

    def should_use_static_analysis(self) -> bool:
        return self.current_strategy == "static_analysis"

    def should_use_diff_only(self) -> bool:
        return self.current_strategy == "pr_diff_only"

    def is_failed(self) -> bool:
        return self.current_strategy == "graceful_failure"

    @staticmethod
    def create_minimal_result(diff_content: Optional[str] = None) -> dict:
        return {
            "fallback": True,
            "strategy": "pr_diff_only",
            "message": "Context retrieval unavailable; using PR diff only",
            "diff_content": diff_content or "",
        }


retrieval_fallback = RetrievalFallback()
