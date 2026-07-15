from abc import ABC, abstractmethod
from typing import Optional

from app.retrieval.models import RetrievedContext


class BaseCompressionStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def compress(
        self,
        context: RetrievedContext,
        max_tokens: int,
    ) -> Optional[RetrievedContext]:
        ...

    async def safe_compress(
        self,
        context: RetrievedContext,
        max_tokens: int,
    ) -> Optional[RetrievedContext]:
        try:
            return await self.compress(context, max_tokens)
        except Exception as e:
            return context
