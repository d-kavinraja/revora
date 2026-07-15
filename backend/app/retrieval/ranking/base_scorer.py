from abc import ABC, abstractmethod
from typing import Optional

from app.retrieval.models import RetrievedContext
from app.indexing.models import RepositoryIndex


class BaseScorer(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def weight(self) -> float:
        ...

    @abstractmethod
    async def score(
        self,
        context: RetrievedContext,
        index: Optional[RepositoryIndex] = None,
    ) -> float:
        ...

    async def safe_score(
        self,
        context: RetrievedContext,
        index: Optional[RepositoryIndex] = None,
    ) -> float:
        try:
            return await self.score(context, index)
        except Exception as e:
            return 0.5
