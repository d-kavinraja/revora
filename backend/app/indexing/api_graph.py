import os
import re
from typing import Dict

from app.indexing.models import CodeGraph, GraphNode, GraphEdge

FASTAPI_PATTERNS = [
    r'@(?:app|router)\.(get|post|put|delete|patch|options|head)\s*\(\s*["\']([^"\']+)',
    r'@(?:app|router)\.(get|post|put|delete|patch)\s*\(',
]

FLASK_PATTERNS = [
    r'@(?:app|bp|blueprint)\.route\s*\(\s*["\']([^"\']+)',
    r'@app\.(?:get|post|put|delete)\s*\(\s*["\']([^"\']+)',
]

EXPRESS_PATTERNS = [
    r'(?:app|router)\.(get|post|put|delete|patch|use)\s*\(\s*["\']([^"\']+)',
]

DJANGO_URL_PATTERNS = [
    r'path\s*\(\s*["\']([^"\']+)',
    r'url\s*\(\s*r?["\']([^"\']+)',
]

NEXTJS_API_PATTERNS = [
    r'export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH)',
    r'export\s+(?:const|let|var)\s+(GET|POST|PUT|DELETE|PATCH)',
]


def build_api_graph(repo_path: str) -> CodeGraph:
    graph = CodeGraph()

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__"}]
        for f in files:
            fp = os.path.join(root, f)
            rel_path = os.path.relpath(fp, repo_path)
            file_id = f"file:{rel_path}"

            if not f.endswith((".py", ".js", ".ts", ".tsx", ".jsx")):
                continue

            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue

            endpoints = []

            if f.endswith(".py"):
                for pattern in FASTAPI_PATTERNS + FLASK_PATTERNS + DJANGO_URL_PATTERNS:
                    for m in re.finditer(pattern, content):
                        groups = m.groups()
                        method = groups[0].upper() if len(groups) > 1 else "GET"
                        path = groups[-1] if groups else "/"
                        endpoints.append((method, path))

            if f.endswith((".js", ".ts", ".tsx", ".jsx")):
                for pattern in EXPRESS_PATTERNS + NEXTJS_API_PATTERNS:
                    for m in re.finditer(pattern, content):
                        groups = m.groups()
                        method = groups[0].upper() if len(groups) > 1 else "GET"
                        path = groups[-1] if len(groups) > 1 else "GET"
                        if path.startswith("/"):
                            endpoints.append((method, path))
                        else:
                            endpoints.append((method, f"/{path}"))

            for method, path in endpoints:
                endpoint_id = f"endpoint:{method}:{path}:{rel_path}"
                graph.nodes.append(GraphNode(
                    id=endpoint_id,
                    type="endpoint",
                    name=f"{method} {path}",
                    file_path=rel_path,
                    metadata={"method": method, "path": path},
                ))
                graph.edges.append(GraphEdge(source=file_id, target=endpoint_id, type="defines"))

    return graph
