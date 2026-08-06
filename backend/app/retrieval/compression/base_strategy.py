from abc import ABC, abstractmethod

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
    ) -> RetrievedContext | None:
        ...

    async def safe_compress(
        self,
        context: RetrievedContext,
        max_tokens: int,
    ) -> RetrievedContext | None:
        try:
            return await self.compress(context, max_tokens)
        except Exception:
            return context
