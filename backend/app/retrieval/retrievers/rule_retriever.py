import logging
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever
from app.knowledge.rule_engine import load_rules

logger = logging.getLogger(__name__)


class RuleRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "rule_retriever"

    async def retrieve(
        self,
        config: RetrievalConfig,
        result: RetrievalResult,
    ) -> list[RetrievedContext]:
        repo_id = getattr(result, "_repo_id", None)
        if repo_id is None:
            return []

        try:
            rules = await load_rules(repo_id)
        except Exception as e:
            logger.warning(f"Failed to load rules for {repo_id}: {e}")
            return []

        if not rules:
            return []

        rules_content = "\n".join(f"- {rule}" for rule in rules)

        return [RetrievedContext(
            file_path=".review-rules",
            content=rules_content,
            relevance_score=0.7,
            source="rule",
            metadata={"rule_count": len(rules)},
        )]
