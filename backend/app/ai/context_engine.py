import os
from pathlib import Path
from typing import List, Dict

from app.ai.models import RepositoryContext, LanguageInfo, FrameworkInfo, ChangedFileInfo

LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".go": "Go",
    ".java": "Java",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".cs": "C#",
    ".cpp": "C++",
    ".swift": "Swift",
    ".kt": "Kotlin",
}

class RepositoryContextEngine:
    """Builds structured context from a cloned repository."""

    async def build_context(self, repo_path: str, pr_diff: str) -> RepositoryContext:
        """Build full repository context."""
        context = RepositoryContext()
        context.languages = self._detect_languages(repo_path)
        context.frameworks = self._detect_frameworks(repo_path)
        context.dependencies = self._analyze_dependencies(repo_path)
        context.changed_files = self._analyze_changed_files(pr_diff)
        return context

    def _detect_languages(self, repo_path: str) -> List[LanguageInfo]:
        """Detect programming languages by file extension analysis."""
        skip_dirs = {".git", "node_modules", "venv", ".venv", "__pycache__", "build", "dist"}
        language_counts: Dict[str, int] = {}
        total_files = 0

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
            for file in files:
                ext = Path(file).suffix
                if ext in LANGUAGE_EXTENSIONS:
                    lang = LANGUAGE_EXTENSIONS[ext]
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

    def _detect_frameworks(self, repo_path: str) -> List[FrameworkInfo]:
        frameworks = []
        if os.path.exists(os.path.join(repo_path, "next.config.js")) or os.path.exists(os.path.join(repo_path, "next.config.ts")):
            frameworks.append(FrameworkInfo(name="Next.js"))
        if os.path.exists(os.path.join(repo_path, "manage.py")):
            frameworks.append(FrameworkInfo(name="Django"))
        # Add basic FastAPI check
        if os.path.exists(os.path.join(repo_path, "requirements.txt")):
            with open(os.path.join(repo_path, "requirements.txt"), 'r') as f:
                content = f.read()
                if "fastapi" in content.lower():
                    frameworks.append(FrameworkInfo(name="FastAPI"))
        return frameworks

    def _analyze_dependencies(self, repo_path: str) -> Dict[str, str]:
        # Stub implementation
        return {}
        
    def _analyze_changed_files(self, pr_diff: str) -> List[ChangedFileInfo]:
        # Basic diff parsing stub
        # Real implementation would parse the diff string into file chunks
        return []

context_engine = RepositoryContextEngine()
