import os
import logging
from typing import List, Set

from app.retrieval.models import RetrievedContext

logger = logging.getLogger(__name__)

MAX_FILE_LINES = 300
MAX_RELATED_FILES = 10


def read_file_content(repo_path: str, file_path: str, max_lines: int = MAX_FILE_LINES) -> str:
    full_path = os.path.join(repo_path, file_path)
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        if len(lines) > max_lines:
            return "".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} more lines truncated]"
        return "".join(lines)
    except OSError:
        return ""


def get_related_files_from_imports(
    changed_files: List[str],
    import_graph_nodes: list,
    import_graph_edges: list,
    repo_path: str,
) -> List[RetrievedContext]:
    related: List[RetrievedContext] = []
    visited: Set[str] = set()

    for changed_file in changed_files:
        file_id = f"file:{changed_file}"
        if file_id in visited:
            continue
        visited.add(file_id)

        for edge in import_graph_edges:
            if edge.source == file_id and edge.type == "imports":
                target_node = next((n for n in import_graph_nodes if n.id == edge.target), None)
                if target_node and target_node.file_path:
                    if target_node.file_path not in visited and target_node.file_path not in changed_files:
                        visited.add(target_node.file_path)
                        content = read_file_content(repo_path, target_node.file_path)
                        if content:
                            related.append(RetrievedContext(
                                file_path=target_node.file_path,
                                content=content,
                                relevance_score=0.8,
                                source="import_graph",
                            ))

        for edge in import_graph_edges:
            if edge.target == file_id and edge.type == "imports":
                source_node = next((n for n in import_graph_nodes if n.id == edge.source), None)
                if source_node and source_node.file_path:
                    if source_node.file_path not in visited and source_node.file_path not in changed_files:
                        visited.add(source_node.file_path)
                        content = read_file_content(repo_path, source_node.file_path)
                        if content:
                            related.append(RetrievedContext(
                                file_path=source_node.file_path,
                                content=content,
                                relevance_score=0.7,
                                source="reverse_import",
                            ))

    return related[:MAX_RELATED_FILES]


def get_related_files_from_calls(
    changed_files: List[str],
    call_graph_nodes: list,
    call_graph_edges: list,
    repo_path: str,
) -> List[RetrievedContext]:
    related: List[RetrievedContext] = []
    visited: Set[str] = set()

    for changed_file in changed_files:
        file_id = f"file:{changed_file}"

        for edge in call_graph_edges:
            if edge.source == file_id and edge.type == "calls":
                target_node = next((n for n in call_graph_nodes if n.id == edge.target), None)
                if target_node and target_node.file_path and target_node.file_path not in visited:
                    if target_node.file_path not in changed_files:
                        visited.add(target_node.file_path)
                        content = read_file_content(repo_path, target_node.file_path, max_lines=150)
                        if content:
                            related.append(RetrievedContext(
                                file_path=target_node.file_path,
                                content=content,
                                relevance_score=0.6,
                                source="call_graph",
                            ))

    return related[:5]


def get_test_files(
    changed_files: List[str],
    test_graph_nodes: list,
    test_graph_edges: list,
    repo_path: str,
) -> List[RetrievedContext]:
    tests: List[RetrievedContext] = []

    for edge in test_graph_edges:
        if edge.type == "tests":
            source_file = edge.target.replace("file:", "")
            if source_file in changed_files:
                test_node = next((n for n in test_graph_nodes if n.id == edge.source), None)
                if test_node and test_node.file_path:
                    content = read_file_content(repo_path, test_node.file_path, max_lines=100)
                    if content:
                        tests.append(RetrievedContext(
                            file_path=test_node.file_path,
                            content=content,
                            relevance_score=0.9,
                            source="test_graph",
                        ))

    return tests[:5]
