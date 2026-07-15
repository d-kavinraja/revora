import logging
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever

logger = logging.getLogger(__name__)


class HistoricalRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "historical_retriever"

    async def retrieve(
        self,
        config: RetrievalConfig,
        result: RetrievalResult,
    ) -> list[RetrievedContext]:
        if not config.enable_historical_context:
            return []

        repo_id = getattr(result, "_repo_id", None)
        if repo_id is None:
            return []

        try:
            from app.models.knowledge import RepositoryKnowledge
            from app.db.session import AsyncSessionLocal
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                query = await db.execute(
                    select(RepositoryKnowledge.content, RepositoryKnowledge.updated_at)
                    .where(
                        RepositoryKnowledge.repo_id == repo_id,
                        RepositoryKnowledge.knowledge_type == "historical_learnings",
                    )
                    .order_by(RepositoryKnowledge.updated_at.desc())
                    .limit(1)
                )
                row = query.first()
        except Exception as e:
            logger.debug(f"Historical retrieval skipped: {e}")
            return []

        if row is None:
            return []

        return [RetrievedContext(
            file_path=".historical-context",
            content=str(row[0]),
            relevance_score=0.5,
            source="historical",
            metadata={
                "knowledge_type": "historical_learnings",
            },
        )]
