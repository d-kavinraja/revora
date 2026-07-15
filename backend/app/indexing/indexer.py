"""Repository indexer.

Builds all code graphs for a repository in parallel.
Uses the shared RepoWalker for efficient filesystem access.
"""

import time
import logging
import asyncio
from typing import Optional

from app.indexing.models import RepositoryIndex, CodeGraph
from app.indexing.dependency_graph import build_import_graph
from app.indexing.call_graph import build_call_graph
from app.indexing.module_graph import build_module_graph
from app.indexing.api_graph import build_api_graph
from app.indexing.db_graph import build_db_graph
from app.indexing.config_graph import build_config_graph
from app.indexing.test_graph import build_test_graph
from app.indexing.metadata_generator import generate_metadata

logger = logging.getLogger(__name__)


class RepositoryIndexer:
    """Builds all code graphs for a repository.

    Graphs are built in parallel for improved performance.
    Each graph builder is wrapped in error handling so a single
    failure does not affect other graphs.
    """

    async def build_index(
        self,
        repo_path: str,
        walker: Optional['RepoWalker'] = None,
    ) -> RepositoryIndex:
        """Build all code graphs for the repository.

        Args:
            repo_path: Path to repository root.
            walker: Optional pre-initialized RepoWalker.

        Returns:
            RepositoryIndex with all graphs populated.
        """
        start = time.time()
        logger.info(f"Starting repository indexing for: {repo_path}")

        index = RepositoryIndex()

        # Initialize walker if not provided
        if walker is None:
            from app.intelligence.repo_walker import RepoWalker
            walker = RepoWalker(repo_path)
            await walker.walk()

        # Build all graphs in parallel
        results = await asyncio.gather(
            self._safe_build("import_graph", build_import_graph, repo_path),
            self._safe_build("call_graph", build_call_graph, repo_path),
            self._safe_build("module_graph", build_module_graph, repo_path),
            self._safe_build("api_graph", build_api_graph, repo_path),
            self._safe_build("db_graph", build_db_graph, repo_path),
            self._safe_build("config_graph", build_config_graph, repo_path),
            self._safe_build("test_graph", build_test_graph, repo_path),
            return_exceptions=True,
        )

        # Assign results to index
        graph_names = [
            "import_graph", "call_graph", "module_graph",
            "api_graph", "db_graph", "config_graph", "test_graph",
        ]

        for i, (name, result) in enumerate(zip(graph_names, results)):
            if isinstance(result, Exception):
                logger.error(f"Graph builder {name} failed: {result}")
                # Leave graph as empty CodeGraph
            elif result is not None:
                setattr(index, name, result)
                logger.info(
                    f"{name}: {len(result.nodes)} nodes, "
                    f"{len(result.edges)} edges"
                )

        # Generate metadata
        index.metadata = generate_metadata(repo_path, index)

        elapsed_ms = (time.time() - start) * 1000
        logger.info(f"Repository indexing completed in {elapsed_ms:.0f}ms")
        index.metadata["indexing_duration_ms"] = elapsed_ms

        return index

    async def _safe_build(
        self,
        name: str,
        build_fn,
        repo_path: str,
    ) -> Optional[CodeGraph]:
        """Safely build a graph with error handling.

        Args:
            name: Graph name for logging.
            build_fn: Graph builder function.
            repo_path: Repository path.

        Returns:
            CodeGraph or None on failure.
        """
        try:
            # Run synchronous builder in thread pool
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, build_fn, repo_path)
        except Exception as e:
            logger.error(f"Graph builder {name} failed: {e}", exc_info=True)
            return None


repository_indexer = RepositoryIndexer()
