"""Dependency analysis engine.

Detects package managers and analyzes dependencies.
Uses the shared RepoWalker for efficient filesystem access.
"""

from typing import Optional

from app.intelligence.models import PackageManagerInfo
from app.intelligence.base_detector import BaseDetector, DetectorResult


PACKAGE_MANAGERS = {
    "npm": {"lock": "package-lock.json", "config": "package.json"},
    "yarn": {"lock": "yarn.lock", "config": "package.json"},
    "pnpm": {"lock": "pnpm-lock.yaml", "config": "package.json"},
    "bun": {"lock": "bun.lockb", "config": "package.json"},
    "pip": {"lock": "requirements.txt", "config": "requirements.txt"},
    "poetry": {"lock": "poetry.lock", "config": "pyproject.toml"},
    "uv": {"lock": "uv.lock", "config": "pyproject.toml"},
    "pdm": {"lock": "pdm.lock", "config": "pyproject.toml"},
    "cargo": {"lock": "Cargo.lock", "config": "Cargo.toml"},
    "go": {"lock": "go.sum", "config": "go.mod"},
    "maven": {"lock": None, "config": "pom.xml"},
    "gradle": {"lock": None, "config": "build.gradle"},
    "bundler": {"lock": "Gemfile.lock", "config": "Gemfile"},
    "composer": {"lock": "composer.lock", "config": "composer.json"},
    "mix": {"lock": "mix.lock", "config": "mix.exs"},
}


class DependencyAnalyzer(BaseDetector):
    """Detects package managers and analyzes dependencies."""

    @property
    def name(self) -> str:
        return "dependency_analyzer"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect package managers using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with package manager info.
        """
        detected_pm: Optional[str] = None
        lock_file: Optional[str] = None

        for pm_name, pm_info in PACKAGE_MANAGERS.items():
            # Check for lock file
            if pm_info["lock"]:
                lock_files = [
                    fp for fp in walker.file_paths
                    if fp.endswith("/" + pm_info["lock"]) or fp == pm_info["lock"]
                ]
                if lock_files:
                    detected_pm = pm_name
                    lock_file = pm_info["lock"]
                    break

            # Check for config file
            if pm_info["config"]:
                config_files = [
                    fp for fp in walker.file_paths
                    if fp.endswith("/" + pm_info["config"]) or fp == pm_info["config"]
                ]
                if config_files:
                    detected_pm = pm_name
                    lock_file = pm_info["lock"]
                    break

        return DetectorResult(
            success=True,
            data={
                "name": detected_pm or "",
                "lock_file": lock_file or "",
            },
            confidence=0.9 if detected_pm else 0.0,
        )


# Legacy function interface for backward compatibility
def detect_package_manager(repo_path: str) -> Optional[PackageManagerInfo]:
    """Detect package manager in a repository (legacy interface)."""
    import asyncio
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = DependencyAnalyzer()
        result = await detector.detect(walker)
        data = result.data
        if not data.get("name"):
            return None
        return PackageManagerInfo(
            name=data["name"],
            lock_file=data.get("lock_file", ""),
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _detect()).result()
        else:
            return loop.run_until_complete(_detect())
    except RuntimeError:
        return asyncio.run(_detect())
