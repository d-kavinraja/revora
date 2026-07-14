"""Data models for code graph indexing.

Provides graph structures for representing code relationships:
import graphs, call graphs, module graphs, API graphs, etc.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class GraphNode:
    """A node in a code graph."""
    id: str
    type: str  # function, class, module, file, endpoint, table, variable
    name: str
    file_path: str
    line_start: int = 0
    line_end: int = 0
    parent_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    """An edge in a code graph."""
    source: str
    target: str
    type: str  # imports, calls, inherits, references, defines, exports, uses
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)


@dataclass
class CodeGraph:
    """A code graph with nodes and edges.

    Provides O(1) node lookup via internal index.
    """
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)

    # Internal indexes for O(1) lookups
    _node_index: Dict[str, GraphNode] = field(default_factory=dict, repr=False)
    _edges_from_index: Dict[str, List[GraphEdge]] = field(default_factory=dict, repr=False)
    _edges_to_index: Dict[str, List[GraphEdge]] = field(default_factory=dict, repr=False)
    _built: bool = field(default=False, repr=False)

    def _build_indexes(self) -> None:
        """Build internal indexes for O(1) lookups."""
        if self._built:
            return

        self._node_index = {n.id: n for n in self.nodes}
        self._edges_from_index = {}
        self._edges_to_index = {}

        for e in self.edges:
            if e.source not in self._edges_from_index:
                self._edges_from_index[e.source] = []
            self._edges_from_index[e.source].append(e)

            if e.target not in self._edges_to_index:
                self._edges_to_index[e.target] = []
            self._edges_to_index[e.target].append(e)

        self._built = True

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID in O(1) time.

        Args:
            node_id: Node identifier.

        Returns:
            GraphNode or None if not found.
        """
        self._build_indexes()
        return self._node_index.get(node_id)

    def get_edges_from(self, node_id: str) -> List[GraphEdge]:
        """Get all edges from a node in O(1) time.

        Args:
            node_id: Source node identifier.

        Returns:
            List of outgoing edges.
        """
        self._build_indexes()
        return self._edges_from_index.get(node_id, [])

    def get_edges_to(self, node_id: str) -> List[GraphEdge]:
        """Get all edges to a node in O(1) time.

        Args:
            node_id: Target node identifier.

        Returns:
            List of incoming edges.
        """
        self._build_indexes()
        return self._edges_to_index.get(node_id, [])

    def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph.

        Args:
            node: Node to add.
        """
        self.nodes.append(node)
        self._built = False  # Invalidate index

    def add_edge(self, edge: GraphEdge) -> None:
        """Add an edge to the graph.

        Args:
            edge: Edge to add.
        """
        self.edges.append(edge)
        self._built = False  # Invalidate index

    def node_count(self) -> int:
        """Get the number of nodes."""
        return len(self.nodes)

    def edge_count(self) -> int:
        """Get the number of edges."""
        return len(self.edges)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type,
                    "name": n.name,
                    "file_path": n.file_path,
                    "line_start": n.line_start,
                    "line_end": n.line_end,
                    "metadata": n.metadata,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "type": e.type,
                    "weight": e.weight,
                }
                for e in self.edges
            ],
        }


@dataclass
class RepositoryIndex:
    """Complete repository index with all code graphs."""
    file_graph: CodeGraph = field(default_factory=CodeGraph)
    import_graph: CodeGraph = field(default_factory=CodeGraph)
    call_graph: CodeGraph = field(default_factory=CodeGraph)
    module_graph: CodeGraph = field(default_factory=CodeGraph)
    api_graph: CodeGraph = field(default_factory=CodeGraph)
    db_graph: CodeGraph = field(default_factory=CodeGraph)
    config_graph: CodeGraph = field(default_factory=CodeGraph)
    test_graph: CodeGraph = field(default_factory=CodeGraph)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "file_graph": self.file_graph.to_dict(),
            "import_graph": self.import_graph.to_dict(),
            "call_graph": self.call_graph.to_dict(),
            "module_graph": self.module_graph.to_dict(),
            "api_graph": self.api_graph.to_dict(),
            "db_graph": self.db_graph.to_dict(),
            "config_graph": self.config_graph.to_dict(),
            "test_graph": self.test_graph.to_dict(),
            "metadata": self.metadata,
        }
