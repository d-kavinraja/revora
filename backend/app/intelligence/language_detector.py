"""Language detection engine.

Detects programming languages by analyzing file extensions.
Uses the shared RepoWalker for efficient filesystem access.
"""

from typing import Dict, List
from collections import defaultdict

from app.intelligence.models import LanguageInfo
from app.intelligence.base_detector import BaseDetector, DetectorResult


# Extension to language mapping
EXTENSION_MAP = {
    ".py": "Python", ".pyi": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript (React)",
    ".js": "JavaScript", ".jsx": "JavaScript (React)",
    ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".go": "Go",
    ".java": "Java",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".cs": "C#",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
    ".c": "C", ".h": "C",
    ".swift": "Swift",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".php": "PHP",
    ".lua": "Lua",
    ".r": "R", ".R": "R",
    ".scala": "Scala",
    ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang",
    ".hs": "Haskell",
    ".dart": "Dart",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".sql": "SQL",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
    ".xml": "XML",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".less": "LESS",
    ".md": "Markdown",
    ".dockerfile": "Dockerfile",
    ".tf": "Terraform", ".hcl": "HCL",
    ".proto": "Protocol Buffers",
    ".graphql": "GraphQL", ".gql": "GraphQL",
}


class LanguageDetector(BaseDetector):
    """Detects programming languages by file extension."""

    @property
    def name(self) -> str:
        return "language_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect languages using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with language distribution.
        """
        language_counts: Dict[str, int] = defaultdict(int)
        total_files = 0

        for file_path in walker.file_paths:
            # Handle Dockerfile specially
            filename = file_path.split("/")[-1].split("\\")[-1]
            if filename.lower() == "dockerfile":
                lang = "Dockerfile"
            else:
                # Get extension
                dot_idx = filename.rfind(".")
                if dot_idx >= 0:
                    ext = filename[dot_idx:].lower()
                    lang = EXTENSION_MAP.get(ext)
                else:
                    lang = None

            if lang:
                language_counts[lang] += 1
                total_files += 1

        if total_files == 0:
            return DetectorResult(
                success=True,
                data={"languages": [], "total_files": 0},
                confidence=0.0,
            )

        languages = [
            LanguageInfo(
                name=lang,
                file_count=count,
                percentage=round(count / total_files * 100, 1),
            )
            for lang, count in sorted(
                language_counts.items(), key=lambda x: -x[1]
            )
        ]

        return DetectorResult(
            success=True,
            data={
                "languages": languages,
                "total_files": total_files,
                "language_count": len(languages),
            },
            confidence=min(1.0, len(languages) * 0.2),
        )


# Legacy function interface for backward compatibility
def detect_languages(repo_path: str) -> List[LanguageInfo]:
    """Detect languages in a repository (legacy interface).

    Args:
        repo_path: Path to repository root.

    Returns:
        List of LanguageInfo objects.
    """
    import asyncio
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = LanguageDetector()
        result = await detector.detect(walker)
        return result.data.get("languages", [])

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context, create a new task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _detect()).result()
        else:
            return loop.run_until_complete(_detect())
    except RuntimeError:
        return asyncio.run(_detect())
