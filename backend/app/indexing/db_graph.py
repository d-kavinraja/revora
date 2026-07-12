import os
import re

from app.indexing.models import CodeGraph, GraphNode, GraphEdge

ORM_PATTERNS = {
    "sqlalchemy": [
        r"class\s+(\w+)\s*\(\s*(?:Base|DeclarativeBase|db\.Model)",
        r"(?:Column|mapped_column)\s*\(",
        r"Relationship\s*\(",
    ],
    "prisma": [
        r"model\s+(\w+)\s*\{",
    ],
    "typeorm": [
        r"@(?:Entity|Table)\s*\(\s*[\"'](\w+)[\"']",
        r"@(?:Column|PrimaryGeneratedColumn)\s*\(",
    ],
    "mongoose": [
        r"new\s+Schema\s*\(",
        r'mongoose\.model\s*\(\s*["\'](\w+)["\']',
    ],
    "django": [
        r'class\s+(\w+)\s*\(\s*(?:models\.Model)',
        r'(?:models\.\w+Field)\s*\(',
    ],
}


def build_db_graph(repo_path: str) -> CodeGraph:
    graph = CodeGraph()

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__"}]
        for f in files:
            if not f.endswith((".py", ".ts", ".js")):
                continue

            fp = os.path.join(root, f)
            rel_path = os.path.relpath(fp, repo_path)
            file_id = f"file:{rel_path}"

            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue

            for orm_name, patterns in ORM_PATTERNS.items():
                for pattern in patterns:
                    for m in re.finditer(pattern, content):
                        groups = m.groups()
                        if groups and groups[0]:
                            model_name = groups[0]
                            model_id = f"model:{model_name}:{rel_path}"
                            graph.nodes.append(GraphNode(
                                id=model_id,
                                type="table",
                                name=model_name,
                                file_path=rel_path,
                                metadata={"orm": orm_name},
                            ))
                            graph.edges.append(GraphEdge(source=file_id, target=model_id, type="defines"))

    return graph
