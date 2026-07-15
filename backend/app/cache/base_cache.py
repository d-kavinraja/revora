import time
import logging
from abc import ABC, abstractmethod
from typing import Optional, Any

logger = logging.getLogger(__name__)


class BaseCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    async def clear(self) -> None:
        ...

    @abstractmethod
    async def get_or_compute(
        self, key: str, compute_fn, ttl_seconds: Optional[int] = None
    ) -> Any:
        ...


class CacheHit:
    def __init__(self, value: Any, source: str = "cache"):
        self.value = value
        self.source = source
        self.time = time.time()
