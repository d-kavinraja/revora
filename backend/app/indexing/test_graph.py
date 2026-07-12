import os
import re
from typing import Dict

from app.indexing.models import CodeGraph, GraphNode, GraphEdge

TEST_PATTERNS = {
    "python": {
        "file_pattern": re.compile(r"^(test_.*\.py|.*_test\.py|tests?/.*\.py)$"),
        "class_pattern": re.compile(r"class\s+(Test\w+)\s*(?:\(|:)"),
        "func_pattern": re.compile(r"(?:async\s+)?def\s+(test_\w+)\s*\("),
    },
    "javascript": {
        "file_pattern": re.compile(r".*\.(test|spec)\.(js|ts|tsx|jsx)$"),
        "describe_pattern": re.compile(r'describe\s*\(\s*["\'](.+?)["\']'),
        "it_pattern": re.compile(r'(?:it|test)\s*\(\s*["\'](.+?)["\']'),
    },
    "go": {
        "file_pattern": re.compile(r".*_test\.go$"),
        "func_pattern": re.compile(r"func\s+(Test\w+)\s*\("),
    },
}


def build_test_graph(repo_path: str) -> CodeGraph:
    graph = CodeGraph()
    source_to_test: Dict[str, list] = {}

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__"}]
        for f in files:
            fp = os.path.join(root, f)
            rel_path = os.path.relpath(fp, repo_path)
            is_test = False
            language = None

            for lang, patterns in TEST_PATTERNS.items():
                if patterns["file_pattern"].match(f) or patterns["file_pattern"].match(rel_path):
                    is_test = True
                    language = lang
                    break

            if not is_test:
                continue

            test_file_id = f"test_file:{rel_path}"
            graph.nodes.append(GraphNode(
                id=test_file_id,
                type="file",
                name=f,
                file_path=rel_path,
                metadata={"is_test": True, "language": language},
            ))

            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue

            if language == "python":
                for m in re.finditer(TEST_PATTERNS["python"]["class_pattern"], content):
                    test_class_id = f"test_class:{m.group(1)}:{rel_path}"
                    graph.nodes.append(GraphNode(id=test_class_id, type="class", name=m.group(1), file_path=rel_path, parent_id=test_file_id))
                    graph.edges.append(GraphEdge(source=test_file_id, target=test_class_id, type="defines"))

                for m in re.finditer(TEST_PATTERNS["python"]["func_pattern"], content):
                    test_func_id = f"test_func:{m.group(1)}:{rel_path}"
                    graph.nodes.append(GraphNode(id=test_func_id, type="function", name=m.group(1), file_path=rel_path, parent_id=test_file_id))
                    graph.edges.append(GraphEdge(source=test_file_id, target=test_func_id, type="defines"))

            elif language == "javascript":
                for m in re.finditer(TEST_PATTERNS["javascript"]["it_pattern"], content):
                    test_name_id = f"test_case:{m.group(1)}:{rel_path}"
                    graph.nodes.append(GraphNode(id=test_name_id, type="function", name=m.group(1), file_path=rel_path, parent_id=test_file_id))
                    graph.edges.append(GraphEdge(source=test_file_id, target=test_name_id, type="defines"))

            # Heuristic: map test file to source file
            source_name = f.replace("_test.", ".").replace(".test.", ".").replace(".spec.", ".").replace("test_", "")
            source_path = os.path.join(os.path.dirname(fp), source_name)
            if os.path.exists(source_path):
                source_rel = os.path.relpath(source_path, repo_path)
                source_file_id = f"file:{source_rel}"
                graph.edges.append(GraphEdge(source=test_file_id, target=source_file_id, type="tests"))

    return graph
