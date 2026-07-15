import hashlib
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext
from app.retrieval.compression.base_strategy import BaseCompressionStrategy

logger = logging.getLogger(__name__)


class DedupStrategy(BaseCompressionStrategy):
    def __init__(self):
        self._seen_hashes: set[str] = set()

    @property
    def name(self) -> str:
        return "dedup"

    async def compress(
        self,
        context: RetrievedContext,
        max_tokens: int,
    ) -> Optional[RetrievedContext]:
        content_hash = hashlib.sha256(context.content.encode()).hexdigest()[:32]

        if content_hash in self._seen_hashes:
            return None

        path_normalized = context.file_path.replace("\\", "/").lower()
        path_hash = hashlib.sha256(path_normalized.encode()).hexdigest()[:16]

        if path_hash in self._seen_hashes:
            return None

        self._seen_hashes.add(content_hash)
        self._seen_hashes.add(path_hash)

        return context

    def reset(self) -> None:
        self._seen_hashes.clear()
