import os
from typing import Dict

from app.indexing.models import CodeGraph, GraphNode, GraphEdge


def build_module_graph(repo_path: str) -> CodeGraph:
    graph = CodeGraph()
    module_map: Dict[str, str] = {}

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__", "dist", "build"}]

        rel_dir = os.path.relpath(root, repo_path)
        if rel_dir == ".":
            rel_dir = ""

        module_id = f"module:{rel_dir}" if rel_dir else "module:root"
        if module_id not in module_map:
            module_map[module_id] = rel_dir
            dir_name = os.path.basename(root) or os.path.basename(repo_path)
            graph.nodes.append(GraphNode(id=module_id, type="module", name=dir_name, file_path=rel_dir))

        py_files = [f for f in files if f.endswith(".py") and f != "__init__.py"]
        js_files = [f for f in files if f.endswith((".js", ".ts", ".tsx", ".jsx")) and not f.endswith(".d.ts")]

        for f in py_files + js_files:
            fp = os.path.join(root, f)
            rel_path = os.path.relpath(fp, repo_path)
            file_id = f"file:{rel_path}"
            graph.nodes.append(GraphNode(id=file_id, type="file", name=f, file_path=rel_path, parent_id=module_id))
            graph.edges.append(GraphEdge(source=module_id, target=file_id, type="contains"))

    # Build parent-child module relationships
    module_ids = list(module_map.keys())
    for mod_id in module_ids:
        mod_path = module_map[mod_id]
        if not mod_path:
            continue
        parent_path = os.path.dirname(mod_path)
        parent_id = f"module:{parent_path}" if parent_path else "module:root"
        if parent_id in [m for m in module_ids]:
            graph.edges.append(GraphEdge(source=parent_id, target=mod_id, type="contains"))

    return graph
