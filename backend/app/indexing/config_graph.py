import os
import json
from typing import Dict

from app.indexing.models import CodeGraph, GraphNode, GraphEdge


CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".config"}
CONFIG_NAMES = {
    "package.json", "tsconfig.json", "next.config.js", "next.config.ts",
    "vite.config.js", "vite.config.ts", "webpack.config.js",
    "pyproject.toml", "setup.cfg", "setup.py", "Cargo.toml", "go.mod",
    "docker-compose.yml", "docker-compose.yaml", "Dockerfile",
    ".env", ".env.example", ".env.local",
    "alembic.ini", "celeryconfig.py",
    ".eslintrc.js", ".eslintrc.json", ".prettierrc", ".prettierrc.json",
    "jest.config.js", "jest.config.ts", "vitest.config.ts",
    "tailwind.config.js", "tailwind.config.ts",
    "postcss.config.js",
}


def build_config_graph(repo_path: str) -> CodeGraph:
    graph = CodeGraph()

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__"}]
        for f in files:
            if f not in CONFIG_NAMES and not f.endswith(CONFIG_EXTENSIONS):
                continue
            if f.endswith(CONFIG_EXTENSIONS) and f not in CONFIG_NAMES:
                continue

            fp = os.path.join(root, f)
            rel_path = os.path.relpath(fp, repo_path)
            config_id = f"config:{rel_path}"

            graph.nodes.append(GraphNode(
                id=config_id,
                type="config",
                name=f,
                file_path=rel_path,
                metadata={"extension": os.path.splitext(f)[1]},
            ))

            # Try to extract dependencies from config files
            if f == "package.json":
                try:
                    with open(fp, "r") as fh:
                        pkg = json.load(fh)
                    deps = list(pkg.get("dependencies", {}).keys())
                    dev_deps = list(pkg.get("devDependencies", {}).keys())
                    for dep in deps + dev_deps:
                        dep_id = f"dep:{dep}"
                        if not any(n.id == dep_id for n in graph.nodes):
                            graph.nodes.append(GraphNode(id=dep_id, type="dependency", name=dep, file_path=""))
                        graph.edges.append(GraphEdge(source=config_id, target=dep_id, type="declares"))
                except (json.JSONDecodeError, OSError):
                    pass

    return graph
