import time
import logging
from abc import ABC, abstractmethod
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig

logger = logging.getLogger(__name__)


class BaseRetriever(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def retrieve(
        self,
        config: RetrievalConfig,
        result: RetrievalResult,
    ) -> list[RetrievedContext]:
        ...

    async def safe_retrieve(
        self,
        config: RetrievalConfig,
        result: RetrievalResult,
    ) -> list[RetrievedContext]:
        start = time.time()
        try:
            contexts = await self.retrieve(config, result)
            elapsed_ms = (time.time() - start) * 1000
            logger.debug(
                f"Retriever {self.name}: {len(contexts)} items in {elapsed_ms:.0f}ms"
            )
            return contexts
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            logger.warning(
                f"Retriever {self.name} failed after {elapsed_ms:.0f}ms: {e}",
                exc_info=True,
            )
            return []
