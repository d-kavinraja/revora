import pytest
from app.indexing.models import CodeGraph, GraphNode, GraphEdge
from app.retrieval.graph_traversal import GraphTraversalEngine


@pytest.fixture
def sample_graph():
    graph = CodeGraph()
    for i in range(6):
        graph.nodes.append(GraphNode(
            id=f"node:{i}", type="file", name=f"file_{i}.py", file_path=f"src/file_{i}.py"
        ))

    edges = [
        ("node:0", "node:1", "imports"),
        ("node:0", "node:2", "imports"),
        ("node:1", "node:3", "imports"),
        ("node:2", "node:3", "imports"),
        ("node:3", "node:4", "calls"),
        ("node:4", "node:5", "calls"),
    ]
    for src, tgt, etype in edges:
        graph.edges.append(GraphEdge(source=src, target=tgt, type=etype))

    return graph


@pytest.fixture
def traversal():
    return GraphTraversalEngine(max_nodes=100, max_depth=5)


class TestGraphTraversal:
    async def test_bfs_basic(self, traversal, sample_graph):
        result = traversal.bfs(sample_graph, "node:0")
        assert len(result) >= 4
        depths = {nid: d for nid, d in result}
        assert depths.get("node:1") == 1 or depths.get("node:2") == 1

    async def test_bfs_max_depth(self, traversal, sample_graph):
        result = traversal.bfs(sample_graph, "node:0", max_depth=1)
        assert len(result) <= 3
        for _, d in result:
            assert d <= 1

    async def test_dfs_basic(self, traversal, sample_graph):
        result = traversal.dfs(sample_graph, "node:0")
        assert len(result) >= 4

    async def test_k_hop_neighbors(self, traversal, sample_graph):
        one_hop = traversal.k_hop_neighbors(sample_graph, "node:0", k=1)
        assert len(one_hop) == 2

        two_hop = traversal.k_hop_neighbors(sample_graph, "node:0", k=2)
        assert len(two_hop) >= 3

    async def test_shortest_path(self, traversal, sample_graph):
        path = traversal.shortest_path(sample_graph, "node:0", "node:4")
        assert path is not None
        assert path[0] == "node:0"
        assert path[-1] == "node:4"

    async def test_shortest_path_no_path(self, traversal, sample_graph):
        path = traversal.shortest_path(sample_graph, "node:5", "node:0")
        assert path is None

    async def test_shortest_path_same_node(self, traversal, sample_graph):
        path = traversal.shortest_path(sample_graph, "node:0", "node:0")
        assert path == ["node:0"]

    async def test_reachable_nodes(self, traversal, sample_graph):
        reachable = traversal.reachable_nodes(sample_graph, "node:0")
        assert "node:4" in reachable
        assert "node:5" in reachable

    async def test_reachable_nodes_reverse(self, traversal, sample_graph):
        reachable = traversal.reachable_nodes(sample_graph, "node:4", reverse=True)
        assert "node:0" in reachable or "node:3" in reachable

    async def test_reachable_with_edge_filter(self, traversal, sample_graph):
        reachable = traversal.reachable_nodes(
            sample_graph, "node:0", edge_type_filter="imports"
        )
        assert "node:1" in reachable
        assert "node:2" in reachable
        assert "node:3" in reachable
        assert "node:4" not in reachable

    async def test_count_dependents(self, traversal, sample_graph):
        count = traversal.count_dependents(sample_graph, "node:3")
        assert count >= 2

    async def test_count_dependencies(self, traversal, sample_graph):
        count = traversal.count_dependencies(sample_graph, "node:0")
        assert count >= 4

    async def test_empty_graph(self, traversal):
        empty = CodeGraph()
        result = traversal.bfs(empty, "nonexistent")
        assert result == []

        path = traversal.shortest_path(empty, "a", "b")
        assert path is None

    async def test_max_nodes_limit(self, traversal, sample_graph):
        result = traversal.bfs(sample_graph, "node:0", max_nodes=2)
        assert len(result) <= 2

    async def test_find_all_paths(self, traversal, sample_graph):
        paths = traversal.find_all_paths(sample_graph, "node:0", "node:3")
        assert len(paths) >= 1
        for p in paths:
            assert p[0] == "node:0"
            assert p[-1] == "node:3"
