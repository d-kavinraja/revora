"""Single-pass filesystem traversal with cached results.

RepoWalker walks the repository ONCE and caches all results.
All detectors and graph builders receive the same walker instance,
eliminating redundant filesystem I/O.
"""

import os
import fnmatch
import logging
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict

from app.core.constants import SKIP_DIRS, SKIP_EXTENSIONS, MAX_FILE_READ_CHARS

logger = logging.getLogger(__name__)


class RepoWalker:
    """Single-pass filesystem traversal with cached results.

    Walks the repository directory tree once and caches:
    - All file paths (relative to repo root)
    - File contents (lazily loaded, cached after first read)
    - Extension counts
    - Directory structure

    Usage:
        walker = RepoWalker("/path/to/repo")
        await walker.walk()
        files = walker.file_paths
        content = await walker.get_content("src/main.py")
    """

    def __init__(
        self,
        repo_path: str,
        skip_dirs: Optional[Set[str]] = None,
        skip_extensions: Optional[Set[str]] = None,
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.skip_dirs = skip_dirs or set(SKIP_DIRS)
        self.skip_extensions = skip_extensions or set(SKIP_EXTENSIONS)

        # Cached data
        self._file_paths: Optional[List[str]] = None
        self._file_contents: Dict[str, str] = {}
        self._extensions: Optional[Dict[str, int]] = None
        self._dir_structure: Optional[Dict] = None
        self._walked: bool = False

    async def walk(self) -> None:
        """Walk the repository once and cache all results.

        This is the only method that performs filesystem I/O for
        path discovery. File contents are loaded lazily on demand.
        """
        if self._walked:
            return

        if not os.path.isdir(self.repo_path):
            logger.warning(f"Repository path does not exist: {self.repo_path}")
            self._file_paths = []
            self._extensions = {}
            self._walked = True
            return

        file_paths = []
        extensions: Dict[str, int] = defaultdict(int)

        for root, dirs, files in os.walk(self.repo_path):
            # Filter out skipped directories (in-place modification)
            # NOTE: not filtering d.startswith(".") because legitimate
            # directories like .github/workflows must be traversed.
            # SKIP_DIRS covers specific hidden dirs to exclude (.git, .env, etc.)
            dirs[:] = [
                d for d in dirs
                if d not in self.skip_dirs
            ]

            for filename in files:
                # Skip skipped extensions
                _, ext = os.path.splitext(filename)
                if ext.lower() in self.skip_extensions:
                    continue

                # Skip hidden files
                if filename.startswith("."):
                    continue

                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, self.repo_path)

                file_paths.append(rel_path)
                extensions[ext.lower()] += 1

        self._file_paths = sorted(file_paths)
        self._extensions = dict(extensions)
        self._walked = True

        logger.info(
            f"RepoWalker: indexed {len(file_paths)} files "
            f"with {len(extensions)} unique extensions "
            f"in {self.repo_path}"
        )

    @property
    def file_paths(self) -> List[str]:
        """All non-skipped file paths (relative to repo root)."""
        if not self._walked:
            raise RuntimeError("RepoWalker.walk() must be called first")
        return self._file_paths or []

    @property
    def extensions(self) -> Dict[str, int]:
        """Extension -> count mapping."""
        if not self._walked:
            raise RuntimeError("RepoWalker.walk() must be called first")
        return self._extensions or {}

    @property
    def file_count(self) -> int:
        """Total number of indexed files."""
        return len(self.file_paths)

    async def get_content(
        self,
        file_path: str,
        max_chars: int = MAX_FILE_READ_CHARS,
    ) -> str:
        """Get file content with caching and size limit.

        Args:
            file_path: Relative path to the file.
            max_chars: Maximum characters to read.

        Returns:
            File content as string, or empty string on error.
        """
        cache_key = f"{file_path}:{max_chars}"

        if cache_key in self._file_contents:
            return self._file_contents[cache_key]

        full_path = os.path.join(self.repo_path, file_path)

        try:
            # Check file size before reading
            stat = os.stat(full_path)
            if stat.st_size > max_chars * 4:  # Rough char-to-byte ratio
                logger.debug(
                    f"File {file_path} too large ({stat.st_size} bytes), "
                    f"reading first {max_chars} chars"
                )

            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars)

            self._file_contents[cache_key] = content
            return content

        except (OSError, IOError, UnicodeDecodeError) as e:
            logger.debug(f"Failed to read {file_path}: {e}")
            return ""

    def get_files_by_extension(self, ext: str) -> List[str]:
        """Get all files with a specific extension.

        Args:
            ext: Extension to filter by (e.g., ".py", ".js").

        Returns:
            List of relative file paths matching the extension.
        """
        ext = ext.lower()
        return [
            fp for fp in self.file_paths
            if fp.lower().endswith(ext)
        ]

    def get_files_by_pattern(self, pattern: str) -> List[str]:
        """Get files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g., "*.py", "src/**/*.ts").

        Returns:
            List of matching file paths.
        """
        return [
            fp for fp in self.file_paths
            if fnmatch.fnmatch(fp, pattern)
        ]

    def get_files_in_directory(self, dir_path: str) -> List[str]:
        """Get all files under a specific directory.

        Args:
            dir_path: Directory path (relative to repo root).

        Returns:
            List of file paths under the directory.
        """
        dir_path = dir_path.rstrip("/") + "/"
        return [
            fp for fp in self.file_paths
            if fp.startswith(dir_path) or fp == dir_path.rstrip("/")
        ]

    def get_directory_tree(self, max_depth: int = 3) -> Dict:
        """Get directory structure as a nested dict.

        Args:
            max_depth: Maximum depth to traverse.

        Returns:
            Nested dict representing directory structure.
        """
        if self._dir_structure is not None:
            return self._dir_structure

        tree: Dict = {}
        for fp in self.file_paths:
            parts = fp.split(os.sep)
            current = tree
            for i, part in enumerate(parts[:max_depth]):
                if i == len(parts) - 1:
                    current[part] = None  # File
                else:
                    if part not in current:
                        current[part] = {}
                    current[part] = current[part] or {}
                    current = current[part]

        self._dir_structure = tree
        return tree

    def get_language_distribution(self) -> Dict[str, int]:
        """Get file count by programming language.

        Returns:
            Dict mapping language name to file count.
        """
        EXTENSION_TO_LANGUAGE = {
            ".py": "Python",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".java": "Java",
            ".go": "Go",
            ".rs": "Rust",
            ".rb": "Ruby",
            ".php": "PHP",
            ".c": "C",
            ".cpp": "C++",
            ".cs": "C#",
            ".swift": "Swift",
            ".kt": "Kotlin",
            ".scala": "Scala",
            ".r": "R",
            ".R": "R",
            ".m": "Objective-C",
            ".mm": "Objective-C++",
            ".lua": "Lua",
            ".pl": "Perl",
            ".sh": "Shell",
            ".bash": "Shell",
            ".zsh": "Shell",
            ".sql": "SQL",
            ".html": "HTML",
            ".htm": "HTML",
            ".css": "CSS",
            ".scss": "SCSS",
            ".less": "LESS",
            ".json": "JSON",
            ".yaml": "YAML",
            ".yml": "YAML",
            ".toml": "TOML",
            ".xml": "XML",
            ".md": "Markdown",
            ".rst": "reStructuredText",
            ".dockerfile": "Dockerfile",
            ".tf": "Terraform",
            ".hcl": "HCL",
            ".proto": "Protocol Buffers",
            ".graphql": "GraphQL",
            ".gql": "GraphQL",
        }

        distribution: Dict[str, int] = defaultdict(int)
        for ext, count in self.extensions.items():
            language = EXTENSION_TO_LANGUAGE.get(ext, ext.lstrip(".").upper())
            distribution[language] += count

        return dict(distribution)
