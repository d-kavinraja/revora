import os
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever

logger = logging.getLogger(__name__)

DOC_PATTERNS = [
    "README.md", "README.rst", "README.txt",
    "CONTRIBUTING.md", "CONTRIBUTING.rst",
    "CHANGELOG.md", "CHANGELOG.rst",
    "LICENSE", "LICENSE.md",
    "docs/", "documentation/", "wiki/",
    "*.md", "*.rst",
]


class DocumentationRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "documentation_retriever"

    async def retrieve(
        self,
        config: RetrievalConfig,
        result: RetrievalResult,
    ) -> list[RetrievedContext]:
        repo_path = getattr(result, "_repo_path", ".")
        changed_files = getattr(result, "_changed_file_paths", [])

        contexts = []
        changed_dirs = set()
        for cf in changed_files:
            d = os.path.dirname(cf)
            while d and d != ".":
                changed_dirs.add(d)
                d = os.path.dirname(d)
            changed_dirs.add(".")

        doc_files = self._find_docs_in_dirs(repo_path, changed_dirs)

        for doc_path in doc_files[:config.max_related_files]:
            content = self._read_file(repo_path, doc_path, max_lines=100)
            if content:
                relevance = 0.4
                if doc_path.lower() == "readme.md":
                    relevance = 0.6

                contexts.append(RetrievedContext(
                    file_path=doc_path,
                    content=content,
                    relevance_score=relevance,
                    source="documentation",
                    metadata={"doc_type": "readme" if "readme" in doc_path.lower() else "docs"},
                ))

        return contexts

    def _find_docs_in_dirs(self, repo_path: str, dirs: set[str]) -> list[str]:
        doc_files = []
        root_readme = os.path.join(repo_path, "README.md")
        if os.path.exists(root_readme):
            doc_files.append("README.md")

        for d in dirs:
            dir_path = os.path.join(repo_path, d) if d != "." else repo_path
            if not os.path.isdir(dir_path):
                continue
            try:
                for f in os.listdir(dir_path):
                    if f.lower() in ("readme.md", "readme.rst", "readme.txt"):
                        rel = os.path.join(d, f) if d != "." else f
                        if rel not in doc_files:
                            doc_files.append(rel)
                    elif d == "." and f.lower() in ("contributing.md", "changelog.md"):
                        if f not in doc_files:
                            doc_files.append(f)
            except OSError:
                continue

        docs_dir = os.path.join(repo_path, "docs")
        if os.path.isdir(docs_dir):
            try:
                for f in sorted(os.listdir(docs_dir))[:5]:
                    if f.endswith((".md", ".rst")):
                        rel = os.path.join("docs", f)
                        if rel not in doc_files:
                            doc_files.append(rel)
            except OSError:
                pass

        return doc_files

    def _read_file(self, repo_path: str, file_path: str, max_lines: int = 100) -> Optional[str]:
        full_path = os.path.join(repo_path, file_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                return "".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} more lines]"
            return "".join(lines)
        except OSError:
            return None
