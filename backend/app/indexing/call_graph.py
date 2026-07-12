import os
import re
from typing import Dict

from app.indexing.models import CodeGraph, GraphNode, GraphEdge


def build_call_graph(repo_path: str) -> CodeGraph:
    graph = CodeGraph()
    defined_functions: Dict[str, str] = {}
    called_functions: Dict[str, list] = {}

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__"}]
        for f in files:
            fp = os.path.join(root, f)
            rel_path = os.path.relpath(fp, repo_path)
            file_id = f"file:{rel_path}"

            if not f.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java")):
                continue

            graph.nodes.append(GraphNode(id=file_id, type="file", name=f, file_path=rel_path))

            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()
            except OSError:
                continue

            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                if f.endswith(".py"):
                    m = re.match(r"^(\s*)def\s+(\w+)\s*\(", line)
                    if m:
                        func_id = f"func:{rel_path}:{m.group(2)}"
                        defined_functions[m.group(2)] = func_id
                        graph.nodes.append(GraphNode(id=func_id, type="function", name=m.group(2), file_path=rel_path, line_start=i, parent_id=file_id))
                        graph.edges.append(GraphEdge(source=file_id, target=func_id, type="defines"))
                        continue

                    m = re.match(r"^(\s*)class\s+(\w+)", line)
                    if m:
                        class_id = f"class:{rel_path}:{m.group(2)}"
                        graph.nodes.append(GraphNode(id=class_id, type="class", name=m.group(2), file_path=rel_path, line_start=i, parent_id=file_id))
                        graph.edges.append(GraphEdge(source=file_id, target=class_id, type="defines"))

                elif f.endswith((".js", ".ts", ".tsx", ".jsx")):
                    m = re.match(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", stripped)
                    if m:
                        func_id = f"func:{rel_path}:{m.group(1)}"
                        defined_functions[m.group(1)] = func_id
                        graph.nodes.append(GraphNode(id=func_id, type="function", name=m.group(1), file_path=rel_path, line_start=i, parent_id=file_id))
                        graph.edges.append(GraphEdge(source=file_id, target=func_id, type="defines"))
                        continue

                    m = re.match(r"(?:export\s+)?class\s+(\w+)", stripped)
                    if m:
                        class_id = f"class:{rel_path}:{m.group(1)}"
                        graph.nodes.append(GraphNode(id=class_id, type="class", name=m.group(1), file_path=rel_path, line_start=i, parent_id=file_id))
                        graph.edges.append(GraphEdge(source=file_id, target=class_id, type="defines"))

            # Find function calls
            for i, line in enumerate(lines, 1):
                for match in re.finditer(r"\b(\w+)\s*\(", line):
                    func_name = match.group(1)
                    caller_id = file_id
                    if func_name in defined_functions and defined_functions[func_name] != caller_id:
                        graph.edges.append(GraphEdge(source=caller_id, target=defined_functions[func_name], type="calls"))

    return graph
