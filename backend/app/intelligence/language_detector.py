import os
from pathlib import Path
from typing import Dict, List

from app.intelligence.models import LanguageInfo

EXTENSION_MAP = {
    ".py": "Python", ".pyi": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript (React)",
    ".js": "JavaScript", ".jsx": "JavaScript (React)", ".mjs": "JavaScript", ".cjs": "JavaScript",
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
}

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", "build", "dist",
    ".next", ".nuxt", "target", "vendor", ".tox", ".mypy_cache", ".pytest_cache",
    "coverage", "htmlcov", ".eggs", "*.egg-info", "out", ".cache",
}


def detect_languages(repo_path: str) -> List[LanguageInfo]:
    language_counts: Dict[str, int] = {}
    total_files = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for file in files:
            if file == "Dockerfile" or file == "dockerfile":
                lang = "Dockerfile"
            else:
                ext = Path(file).suffix.lower()
                lang = EXTENSION_MAP.get(ext)
            if lang:
                language_counts[lang] = language_counts.get(lang, 0) + 1
                total_files += 1

    if total_files == 0:
        return []

    return [
        LanguageInfo(
            name=lang,
            file_count=count,
            percentage=round(count / total_files * 100, 1),
        )
        for lang, count in sorted(language_counts.items(), key=lambda x: -x[1])
    ]
