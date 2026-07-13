import os
import json
from typing import Dict, Any

from app.indexing.models import RepositoryIndex


def generate_metadata(repo_path: str, index: RepositoryIndex) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}

    # File statistics
    total_files = 0
    total_lines = 0
    file_types: Dict[str, int] = {}

    skip_dirs = {".git", "node_modules", "venv", "__pycache__", "dist", "build"}

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            total_files += 1
            ext = os.path.splitext(f)[1] or "no_ext"
            file_types[ext] = file_types.get(ext, 0) + 1
            try:
                fp = os.path.join(root, f)
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    total_lines += sum(1 for _ in fh)
            except (OSError, UnicodeDecodeError):
                pass

    metadata["total_files"] = total_files
    metadata["total_lines"] = total_lines
    metadata["file_types"] = file_types

    # Graph statistics
    metadata["graph_stats"] = {
        "import_nodes": len(index.import_graph.nodes),
        "import_edges": len(index.import_graph.edges),
        "call_nodes": len(index.call_graph.nodes),
        "call_edges": len(index.call_graph.edges),
        "api_endpoints": len([n for n in index.api_graph.nodes if n.type == "endpoint"]),
        "db_models": len([n for n in index.db_graph.nodes if n.type == "table"]),
        "config_files": len([n for n in index.config_graph.nodes if n.type == "config"]),
        "test_files": len([n for n in index.test_graph.nodes if n.metadata.get("is_test")]),
    }

    # Repository size estimation
    try:
        total_size = 0
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                try:
                    total_size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        metadata["repository_size_bytes"] = total_size
    except Exception:
        metadata["repository_size_bytes"] = 0

    return metadata
