import os
import re
from typing import Dict, Set

from app.indexing.models import CodeGraph, GraphNode, GraphEdge


def build_import_graph(repo_path: str) -> CodeGraph:
    graph = CodeGraph()
    file_imports: Dict[str, Set[str]] = {}

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__", "dist", "build"}]
        for f in files:
            fp = os.path.join(root, f)
            rel_path = os.path.relpath(fp, repo_path)
            file_id = f"file:{rel_path}"

            graph.nodes.append(GraphNode(id=file_id, type="file", name=f, file_path=rel_path))

            if f.endswith((".py",)):
                imports = _parse_python_imports(fp)
            elif f.endswith((".js", ".ts", ".tsx", ".jsx", ".mjs")):
                imports = _parse_js_imports(fp)
            elif f.endswith(".go"):
                imports = _parse_go_imports(fp)
            else:
                imports = set()

            file_imports[file_id] = imports
            for imp in imports:
                target_id = f"module:{imp}"
                if not any(n.id == target_id for n in graph.nodes):
                    graph.nodes.append(GraphNode(id=target_id, type="module", name=imp, file_path=""))
                graph.edges.append(GraphEdge(source=file_id, target=target_id, type="imports"))

    return graph


def _parse_python_imports(fp: str) -> Set[str]:
    imports = set()
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                m = re.match(r"^from\s+([\w.]+)\s+import", line)
                if m:
                    imports.add(m.group(1))
                    continue
                m = re.match(r"^import\s+([\w.]+)", line)
                if m:
                    imports.add(m.group(1))
    except OSError:
        pass
    return imports


def _parse_js_imports(fp: str) -> Set[str]:
    imports = set()
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                m = re.match(r"""(?:import|from)\s+.*?['"](.+?)['"]""", line)
                if m:
                    imports.add(m.group(1))
    except OSError:
        pass
    return imports


def _parse_go_imports(fp: str) -> Set[str]:
    imports = set()
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        for m in re.finditer(r'"([^"]+)"', content):
            imp = m.group(1)
            if "/" in imp:
                imports.add(imp)
    except OSError:
        pass
    return imports
