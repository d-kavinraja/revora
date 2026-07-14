"""Repository metrics engine.

Collects quantitative metrics about the repository:
file counts, line counts, size distribution, etc.
"""

from typing import Dict

from app.intelligence.base_detector import BaseDetector, DetectorResult


class MetricsEngine(BaseDetector):
    """Collects repository metrics."""

    @property
    def name(self) -> str:
        return "metrics_engine"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Collect repository metrics.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with repository metrics.
        """
        # Basic file metrics
        total_files = walker.file_count
        extensions = walker.extensions

        # Language distribution
        language_dist = walker.get_language_distribution()

        # Directory depth analysis
        max_depth = 0
        depth_counts: Dict[int, int] = {}

        for fp in walker.file_paths:
            depth = fp.count("/") + fp.count("\\")
            max_depth = max(max_depth, depth)
            depth_counts[depth] = depth_counts.get(depth, 0) + 1

        # File size distribution (by extension)
        ext_counts = extensions

        # Top directories
        top_dirs: Dict[str, int] = {}
        for fp in walker.file_paths:
            parts = fp.replace("\\", "/").split("/")
            if len(parts) > 1:
                top_dir = parts[0]
                top_dirs[top_dir] = top_dirs.get(top_dir, 0) + 1

        # Sort top directories by count
        sorted_dirs = sorted(top_dirs.items(), key=lambda x: -x[1])[:10]

        return DetectorResult(
            success=True,
            data={
                "total_files": total_files,
                "total_extensions": len(extensions),
                "language_distribution": language_dist,
                "max_directory_depth": max_depth,
                "depth_distribution": depth_counts,
                "extension_counts": ext_counts,
                "top_directories": dict(sorted_dirs),
                "file_types": {
                    "code": sum(
                        ext_counts.get(ext, 0)
                        for ext in [".py", ".js", ".ts", ".tsx", ".jsx",
                                    ".go", ".java", ".rb", ".rs", ".cs"]
                    ),
                    "config": sum(
                        ext_counts.get(ext, 0)
                        for ext in [".json", ".yaml", ".yml", ".toml",
                                    ".ini", ".cfg", ".xml"]
                    ),
                    "documentation": sum(
                        ext_counts.get(ext, 0)
                        for ext in [".md", ".rst", ".txt"]
                    ),
                    "other": total_files - sum(
                        ext_counts.get(ext, 0)
                        for ext in [".py", ".js", ".ts", ".tsx", ".jsx",
                                    ".go", ".java", ".rb", ".rs", ".cs",
                                    ".json", ".yaml", ".yml", ".toml",
                                    ".ini", ".cfg", ".xml",
                                    ".md", ".rst", ".txt"]
                    ),
                },
            },
            confidence=1.0,
        )
