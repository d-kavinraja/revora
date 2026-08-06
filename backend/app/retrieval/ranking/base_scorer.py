from abc import ABC, abstractmethod

from app.indexing.models import RepositoryIndex
from app.retrieval.models import RetrievedContext


class BaseScorer(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def weight(self) -> float: ...

    @abstractmethod
    async def score(
        self,
        context: RetrievedContext,
        index: RepositoryIndex | None = None,
    ) -> float: ...

    async def safe_score(
        self,
        context: RetrievedContext,
        index: RepositoryIndex | None = None,
    ) -> float:
        try:
            return await self.score(context, index)
        except Exception:
            return 0.5
