from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GraphNode:
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
    source: str
    target: str
    type: str  # imports, calls, inherits, references, defines, exports, uses
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)


@dataclass
class CodeGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def get_edges_from(self, node_id: str) -> list[GraphEdge]:
        return [e for e in self.edges if e.source == node_id]

    def get_edges_to(self, node_id: str) -> list[GraphEdge]:
        return [e for e in self.edges if e.target == node_id]

    def to_dict(self) -> dict:
        return {
            "nodes": [{"id": n.id, "type": n.type, "name": n.name, "file_path": n.file_path, "line_start": n.line_start, "line_end": n.line_end, "metadata": n.metadata} for n in self.nodes],
            "edges": [{"source": e.source, "target": e.target, "type": e.type, "weight": e.weight} for e in self.edges],
        }


@dataclass
class SearchResult:
    node: GraphNode
    score: float
    context: str = ""


@dataclass
class RepositoryIndex:
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
