"""Base graph builder interface for code graph indexing.

All graph builders must implement this interface to ensure
consistent behavior and enable parallel execution.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import time
import logging

from app.indexing.models import CodeGraph

logger = logging.getLogger(__name__)


@dataclass
class GraphBuildResult:
    """Result from a graph builder."""
    success: bool
    graph: Optional[CodeGraph] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    builder_name: str = ""
    node_count: int = 0
    edge_count: int = 0

    def to_dict(self):
        """Convert to dictionary."""
        return {
            "success": self.success,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "builder_name": self.builder_name,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
        }


class BaseGraphBuilder(ABC):
    """Interface for all code graph builders.

    Each builder constructs a specific type of code graph
    (import, call, module, API, DB, config, test) from
    repository files.

    Subclasses must implement:
        - name: Graph name for logging
        - build(walker): Build the graph from repository files
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Graph name for logging and metrics."""
        ...

    @abstractmethod
    async def build(self, walker: 'RepoWalker') -> CodeGraph:
        """Build the code graph from repository files.

        Args:
            walker: Pre-initialized RepoWalker with cached filesystem data.

        Returns:
            CodeGraph containing nodes and edges.
        """
        ...

    def validate_graph(self, graph: CodeGraph) -> bool:
        """Optional validation of graph structure.

        Override to add custom validation logic.

        Args:
            graph: The graph to validate.

        Returns:
            True if graph is valid, False otherwise.
        """
        return True

    async def safe_build(self, walker: 'RepoWalker') -> GraphBuildResult:
        """Wrapper around build() with timing and error handling.

        This method should be called by the indexer, not directly.
        It ensures every builder failure is caught and logged.

        Args:
            walker: Pre-initialized RepoWalker.

        Returns:
            GraphBuildResult, never raises exceptions.
        """
        start = time.time()
        try:
            graph = await self.build(walker)
            duration_ms = (time.time() - start) * 1000

            if not self.validate_graph(graph):
                logger.warning(f"Graph builder {self.name} produced invalid graph")
                return GraphBuildResult(
                    success=False,
                    error="Graph validation failed",
                    duration_ms=duration_ms,
                    builder_name=self.name,
                )

            return GraphBuildResult(
                success=True,
                graph=graph,
                duration_ms=duration_ms,
                builder_name=self.name,
                node_count=len(graph.nodes),
                edge_count=len(graph.edges),
            )

        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            logger.error(
                f"Graph builder {self.name} failed after {duration_ms:.0f}ms: {e}",
                exc_info=True,
            )
            return GraphBuildResult(
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                builder_name=self.name,
            )
