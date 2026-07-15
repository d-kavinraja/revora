import os
import logging
from typing import Optional

from app.retrieval.models import RetrievedContext, RetrievalResult, RetrievalConfig
from app.retrieval.retrievers.base_retriever import BaseRetriever
from app.indexing.models import RepositoryIndex

logger = logging.getLogger(__name__)

SECURITY_PATTERNS = [
    "auth", "login", "password", "token", "jwt", "oauth",
    "permission", "role", "rbac", "acl", "session",
    "cors", "csrf", "xss", "injection", "sanitize",
    "encrypt", "decrypt", "hash", "secret", "credential",
    "ssl", "tls", "https", "certificate",
    "rate.limit", "throttle", "firewall", "audit",
    "validator", "middleware", "guard",
]


class SecurityRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "security_retriever"

    async def retrieve(
        self,
        config: RetrievalConfig,
        result: RetrievalResult,
    ) -> list[RetrievedContext]:
        index: Optional[RepositoryIndex] = getattr(result, "_index", None)
        repo_path = getattr(result, "_repo_path", ".")
        changed_files = getattr(result, "_changed_file_paths", [])

        changed_are_security = any(
            any(pattern in cf.lower() for pattern in SECURITY_PATTERNS)
            for cf in changed_files
        )

        if not changed_are_security and not config.enable_security_context:
            return []

        contexts = []
        security_files: set[str] = set()

        for fp_path in getattr(result, "_all_files", []) or self._find_files(repo_path):
            rel = fp_path if not fp_path.startswith(repo_path) else os.path.relpath(fp_path, repo_path)
            if any(pattern in rel.lower() for pattern in SECURITY_PATTERNS):
                if rel not in changed_files:
                    security_files.add(rel)

        for sec_file in list(security_files)[:config.max_related_files]:
            content = self._read_file(repo_path, sec_file, max_lines=200)
            if content:
                contexts.append(RetrievedContext(
                    file_path=sec_file,
                    content=content,
                    relevance_score=0.65,
                    source="security",
                    metadata={"security_file": True},
                ))

        return contexts

    def _find_files(self, repo_path: str) -> list[str]:
        files = []
        try:
            for root, dirs, fnames in os.walk(repo_path):
                dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", "venv"}]
                for f in fnames:
                    files.append(os.path.join(root, f))
        except OSError:
            pass
        return files

    def _read_file(self, repo_path: str, file_path: str, max_lines: int = 200) -> Optional[str]:
        full_path = os.path.join(repo_path, file_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                return "".join(lines[:max_lines]) + f"\n... [{len(lines) - max_lines} more lines]"
            return "".join(lines)
        except OSError:
            return None
