import time
import logging
from typing import Dict, Any

from app.indexing.models import RepositoryIndex
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
    """Builds all code graphs for a repository."""

    async def build_index(self, repo_path: str) -> RepositoryIndex:
        start = time.time()
        logger.info(f"Starting repository indexing for: {repo_path}")

        index = RepositoryIndex()

        index.import_graph = build_import_graph(repo_path)
        logger.info(f"Import graph: {len(index.import_graph.nodes)} nodes, {len(index.import_graph.edges)} edges")

        index.call_graph = build_call_graph(repo_path)
        logger.info(f"Call graph: {len(index.call_graph.nodes)} nodes, {len(index.call_graph.edges)} edges")

        index.module_graph = build_module_graph(repo_path)
        logger.info(f"Module graph: {len(index.module_graph.nodes)} nodes, {len(index.module_graph.edges)} edges")

        index.api_graph = build_api_graph(repo_path)
        logger.info(f"API graph: {len(index.api_graph.nodes)} nodes, {len(index.api_graph.edges)} edges")

        index.db_graph = build_db_graph(repo_path)
        logger.info(f"DB graph: {len(index.db_graph.nodes)} nodes, {len(index.db_graph.edges)} edges")

        index.config_graph = build_config_graph(repo_path)
        logger.info(f"Config graph: {len(index.config_graph.nodes)} nodes, {len(index.config_graph.edges)} edges")

        index.test_graph = build_test_graph(repo_path)
        logger.info(f"Test graph: {len(index.test_graph.nodes)} nodes, {len(index.test_graph.edges)} edges")

        index.metadata = generate_metadata(repo_path, index)

        elapsed_ms = (time.time() - start) * 1000
        logger.info(f"Repository indexing completed in {elapsed_ms:.0f}ms")
        index.metadata["indexing_duration_ms"] = elapsed_ms

        return index


repository_indexer = RepositoryIndexer()
