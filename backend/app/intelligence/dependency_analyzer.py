# ruff: noqa: F821
"""Dependency analysis engine.

Detects package managers and analyzes dependencies.
Uses the shared RepoWalker for efficient filesystem access.
"""


from app.intelligence._async_util import run_async
from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.intelligence.models import PackageManagerInfo

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

    async def detect(self, walker: "RepoWalker") -> DetectorResult:
        """Detect package managers using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with package manager info.
        """
        import os as _os

        detected_pm: str | None = None
        lock_file: str | None = None

        # First pass: check lock files only (lock files are more specific)
        for pm_name, pm_info in PACKAGE_MANAGERS.items():
            if pm_info["lock"]:
                lock_files = [
                    fp
                    for fp in walker.file_paths
                    if fp.endswith(("/" + pm_info["lock"], _os.sep + pm_info["lock"]))
                    or fp == pm_info["lock"]
                ]
                if lock_files:
                    detected_pm = pm_name
                    lock_file = pm_info["lock"]
                    break

        # Second pass: check config files only (if no lock file was found)
        if not detected_pm:
            for pm_name, pm_info in PACKAGE_MANAGERS.items():
                if pm_info["config"]:
                    config_files = [
                        fp
                        for fp in walker.file_paths
                        if fp.endswith(
                            ("/" + pm_info["config"], _os.sep + pm_info["config"])
                        )
                        or fp == pm_info["config"]
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
def detect_package_manager(repo_path: str) -> PackageManagerInfo | None:
    """Detect package manager in a repository (legacy interface)."""
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

    return run_async(_detect())
