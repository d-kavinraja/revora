import time
import hashlib
import logging
from typing import Optional

from app.cache.redis_cache import redis_cache
from app.cache.memory_cache import memory_cache
from app.indexing.models import RepositoryIndex, CodeGraph, GraphNode, GraphEdge

logger = logging.getLogger(__name__)


class GraphCache:
    def __init__(self, default_ttl: int = 3600):
        self._default_ttl = default_ttl

    async def get_index(
        self,
        repo_id: str,
        commit_sha: Optional[str] = None,
    ) -> Optional[RepositoryIndex]:
        key = self._build_key(repo_id, commit_sha)
        cached = await redis_cache.get(key)
        if cached is not None:
            return self._deserialize_index(cached)
        return None

    async def set_index(
        self,
        repo_id: str,
        index: RepositoryIndex,
        commit_sha: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> None:
        key = self._build_key(repo_id, commit_sha)
        serialized = self._serialize_index(index)
        await redis_cache.set(key, serialized, ttl or self._default_ttl)

    async def invalidate(self, repo_id: str, commit_sha: Optional[str] = None) -> None:
        key = self._build_key(repo_id, commit_sha)
        await redis_cache.delete(key)
        await memory_cache.delete(key)

    async def has_index(self, repo_id: str, commit_sha: Optional[str] = None) -> bool:
        key = self._build_key(repo_id, commit_sha)
        return await redis_cache.exists(key)

    def _build_key(self, repo_id: str, commit_sha: Optional[str] = None) -> str:
        raw = f"graph_index:{repo_id}:{commit_sha or 'latest'}"
        return f"cache:graph:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"

    def _serialize_index(self, index: RepositoryIndex) -> dict:
        return {
            "metadata": index.metadata,
            "graphs": {
                name: self._serialize_graph(getattr(index, name, CodeGraph()))
                for name in [
                    "import_graph", "call_graph", "module_graph",
                    "api_graph", "db_graph", "config_graph", "test_graph",
                ]
            },
        }

    def _serialize_graph(self, graph: CodeGraph) -> dict:
        return {
            "nodes": [
                {
                    "id": n.id, "type": n.type, "name": n.name,
                    "file_path": n.file_path,
                    "line_start": n.line_start, "line_end": n.line_end,
                    "parent_id": n.parent_id, "metadata": n.metadata,
                }
                for n in graph.nodes
            ],
            "edges": [
                {
                    "source": e.source, "target": e.target,
                    "type": e.type, "weight": e.weight,
                    "metadata": e.metadata,
                }
                for e in graph.edges
            ],
        }

    def _deserialize_index(self, data: dict) -> RepositoryIndex:
        index = RepositoryIndex()
        if data.get("metadata"):
            index.metadata = data["metadata"]

        for graph_name, graph_data in data.get("graphs", {}).items():
            graph = CodeGraph()
            for node_data in graph_data.get("nodes", []):
                graph.nodes.append(GraphNode(
                    id=node_data["id"],
                    type=node_data["type"],
                    name=node_data["name"],
                    file_path=node_data.get("file_path", ""),
                    line_start=node_data.get("line_start", 0),
                    line_end=node_data.get("line_end", 0),
                    parent_id=node_data.get("parent_id"),
                    metadata=node_data.get("metadata", {}),
                ))
            for edge_data in graph_data.get("edges", []):
                graph.edges.append(GraphEdge(
                    source=edge_data["source"],
                    target=edge_data["target"],
                    type=edge_data.get("type", "references"),
                    weight=edge_data.get("weight", 1.0),
                    metadata=edge_data.get("metadata", {}),
                ))
            setattr(index, graph_name, graph)

        return index


graph_cache = GraphCache()
