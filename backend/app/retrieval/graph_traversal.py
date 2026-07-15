from collections import deque
from typing import Callable, Optional

from app.indexing.models import CodeGraph, GraphNode, GraphEdge


class GraphTraversalEngine:
    def __init__(self, max_nodes: int = 1000, max_depth: int = 5):
        self._max_nodes = max_nodes
        self._max_depth = max_depth

    def bfs(
        self,
        graph: CodeGraph,
        start_node_id: str,
        max_depth: int = 0,
        max_nodes: int = 0,
        node_filter: Optional[Callable[[GraphNode], bool]] = None,
    ) -> list[tuple[str, int]]:
        actual_depth = max_depth or self._max_depth
        actual_max = max_nodes or self._max_nodes

        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()
        result: list[tuple[str, int]] = []

        queue.append((start_node_id, 0))
        visited.add(start_node_id)

        while queue and len(result) < actual_max:
            current_id, depth = queue.popleft()

            if depth > 0:
                node = graph.get_node(current_id)
                if node_filter is None or node_filter(node):
                    result.append((current_id, depth))

            if depth >= actual_depth:
                continue

            for edge in graph.get_edges_from(current_id):
                if edge.target not in visited:
                    visited.add(edge.target)
                    queue.append((edge.target, depth + 1))

        return result

    def dfs(
        self,
        graph: CodeGraph,
        start_node_id: str,
        max_depth: int = 0,
        max_nodes: int = 0,
        node_filter: Optional[Callable[[GraphNode], bool]] = None,
    ) -> list[tuple[str, int]]:
        actual_depth = max_depth or self._max_depth
        actual_max = max_nodes or self._max_nodes

        visited: set[str] = set()
        stack: list[tuple[str, int]] = []
        result: list[tuple[str, int]] = []

        stack.append((start_node_id, 0))

        while stack and len(result) < actual_max:
            current_id, depth = stack.pop()

            if current_id in visited:
                continue
            visited.add(current_id)

            if depth > 0:
                node = graph.get_node(current_id)
                if node_filter is None or node_filter(node):
                    result.append((current_id, depth))

            if depth >= actual_depth:
                continue

            for edge in reversed(graph.get_edges_from(current_id)):
                if edge.target not in visited:
                    stack.append((edge.target, depth + 1))

        return result

    def k_hop_neighbors(
        self,
        graph: CodeGraph,
        start_node_id: str,
        k: int = 2,
        node_filter: Optional[Callable[[GraphNode], bool]] = None,
    ) -> list[tuple[str, int]]:
        return self.bfs(
            graph,
            start_node_id,
            max_depth=k,
            node_filter=node_filter,
        )

    def shortest_path(
        self,
        graph: CodeGraph,
        start_node_id: str,
        end_node_id: str,
    ) -> Optional[list[str]]:
        if start_node_id == end_node_id:
            return [start_node_id]

        visited: set[str] = {start_node_id}
        queue: deque[tuple[str, list[str]]] = deque()
        queue.append((start_node_id, [start_node_id]))

        while queue:
            current_id, path = queue.popleft()

            for edge in graph.get_edges_from(current_id):
                if edge.target == end_node_id:
                    return path + [edge.target]
                if edge.target not in visited:
                    visited.add(edge.target)
                    queue.append((edge.target, path + [edge.target]))

        return None

    def reachable_nodes(
        self,
        graph: CodeGraph,
        start_node_id: str,
        edge_type_filter: Optional[str] = None,
        reverse: bool = False,
    ) -> list[str]:
        visited: set[str] = set()
        queue: deque[str] = deque()
        result: list[str] = []

        queue.append(start_node_id)
        visited.add(start_node_id)

        while queue:
            current_id = queue.popleft()
            result.append(current_id)

            edges = (
                graph.get_edges_to(current_id) if reverse
                else graph.get_edges_from(current_id)
            )

            for edge in edges:
                if edge_type_filter and edge.type != edge_type_filter:
                    continue
                neighbor = edge.source if reverse else edge.target
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        return result

    def find_all_paths(
        self,
        graph: CodeGraph,
        start_node_id: str,
        end_node_id: str,
        max_paths: int = 10,
        max_depth: int = 10,
    ) -> list[list[str]]:
        paths: list[list[str]] = []
        stack: list[tuple[str, list[str], set[str]]] = [
            (start_node_id, [start_node_id], {start_node_id})
        ]

        while stack and len(paths) < max_paths:
            current_id, path, visited = stack.pop()

            if len(path) > max_depth:
                continue

            for edge in graph.get_edges_from(current_id):
                if edge.target == end_node_id:
                    paths.append(path + [edge.target])
                    if len(paths) >= max_paths:
                        break
                elif edge.target not in visited:
                    new_visited = visited | {edge.target}
                    stack.append((edge.target, path + [edge.target], new_visited))

        return paths

    def get_leaf_nodes(
        self,
        graph: CodeGraph,
        start_node_id: str,
    ) -> list[str]:
        leaves: list[str] = []
        visited: set[str] = set()
        queue: deque[str] = deque([start_node_id])
        visited.add(start_node_id)

        while queue:
            current_id = queue.popleft()
            edges = graph.get_edges_from(current_id)

            if not edges:
                leaves.append(current_id)
                continue

            has_unvisited = False
            for edge in edges:
                if edge.target not in visited:
                    visited.add(edge.target)
                    queue.append(edge.target)
                    has_unvisited = True

            if not has_unvisited:
                leaves.append(current_id)

        return leaves

    def get_nodes_by_type(
        self,
        graph: CodeGraph,
        node_type: str,
    ) -> list[GraphNode]:
        return [n for n in graph.nodes if n.type == node_type]

    def get_edges_by_type(
        self,
        graph: CodeGraph,
        edge_type: str,
    ) -> list[GraphEdge]:
        return [e for e in graph.edges if e.type == edge_type]

    def count_dependents(
        self,
        graph: CodeGraph,
        node_id: str,
    ) -> int:
        visited: set[str] = set()
        queue: deque[str] = deque([node_id])
        count = 0

        while queue:
            current_id = queue.popleft()
            for edge in graph.get_edges_to(current_id):
                if edge.source not in visited:
                    visited.add(edge.source)
                    queue.append(edge.source)
                    count += 1

        return count

    def count_dependencies(
        self,
        graph: CodeGraph,
        node_id: str,
    ) -> int:
        visited: set[str] = set()
        queue: deque[str] = deque([node_id])
        count = 0

        while queue:
            current_id = queue.popleft()
            for edge in graph.get_edges_from(current_id):
                if edge.target not in visited:
                    visited.add(edge.target)
                    queue.append(edge.target)
                    count += 1

        return count


graph_traversal = GraphTraversalEngine()
