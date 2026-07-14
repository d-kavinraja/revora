"""Base detector interface for the Repository Intelligence Engine.

All intelligence detectors must implement this interface to ensure
consistent behavior and enable parallel execution with error isolation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class DetectorResult:
    """Standard result from any intelligence detector."""
    success: bool
    data: Dict[str, Any]
    confidence: float = 0.0
    error: Optional[str] = None
    duration_ms: float = 0.0
    detector_name: str = ""
    detector_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "data": self.data,
            "confidence": self.confidence,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "detector_name": self.detector_name,
            "detector_version": self.detector_version,
        }


class BaseDetector(ABC):
    """Interface for all intelligence detectors.

    Each detector analyzes a specific aspect of the repository
    without making any LLM calls. All analysis is deterministic.

    Subclasses must implement:
        - name: Unique detector name
        - version: Detector version for cache invalidation
        - detect(walker): Run detection using the shared RepoWalker
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique detector name for logging and metrics."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Detector version for cache invalidation."""
        ...

    @abstractmethod
    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Run detection using the shared RepoWalker cache.

        Args:
            walker: Pre-initialized RepoWalker with cached filesystem data.

        Returns:
            DetectorResult with success status, data, and confidence score.
        """
        ...

    def validate_result(self, result: DetectorResult) -> bool:
        """Optional validation of detector output.

        Override to add custom validation logic.
        Default implementation checks success flag.

        Args:
            result: The detector result to validate.

        Returns:
            True if result is valid, False otherwise.
        """
        return result.success

    async def safe_detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Wrapper around detect() with timing and error handling.

        This method should be called by the engine, not directly.
        It ensures every detector failure is caught and logged.

        Args:
            walker: Pre-initialized RepoWalker.

        Returns:
            DetectorResult, never raises exceptions.
        """
        start = time.time()
        try:
            result = await self.detect(walker)
            result.duration_ms = (time.time() - start) * 1000
            result.detector_name = self.name
            result.detector_version = self.version

            if not self.validate_result(result):
                logger.warning(
                    f"Detector {self.name} produced invalid result"
                )
                result.success = False
                result.error = "Result validation failed"

            return result

        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            logger.error(
                f"Detector {self.name} failed after {duration_ms:.0f}ms: {e}",
                exc_info=True,
            )
            return DetectorResult(
                success=False,
                data={},
                confidence=0.0,
                error=str(e),
                duration_ms=duration_ms,
                detector_name=self.name,
                detector_version=self.version,
            )
