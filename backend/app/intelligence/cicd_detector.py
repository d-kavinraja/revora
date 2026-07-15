"""CI/CD detection engine.

Detects CI/CD providers from configuration files.
Uses the shared RepoWalker for efficient filesystem access.
"""

from typing import List, Optional

from app.intelligence.models import CIInfo
from app.intelligence.base_detector import BaseDetector, DetectorResult


CI_PROVIDERS = {
    "github_actions": {
        "directory": ".github/workflows",
        "extensions": [".yml", ".yaml"],
    },
    "gitlab_ci": {
        "files": [".gitlab-ci.yml"],
    },
    "circleci": {
        "directory": ".circleci",
        "files": ["config.yml"],
    },
    "jenkins": {
        "files": ["Jenkinsfile"],
    },
    "travis_ci": {
        "files": [".travis.yml"],
    },
    "azure_pipelines": {
        "files": ["azure-pipelines.yml"],
    },
    "bitbucket": {
        "files": ["bitbucket-pipelines.yml"],
    },
    "drone": {
        "files": [".drone.yml"],
    },
}


class CICDDetector(BaseDetector):
    """Detects CI/CD providers."""

    @property
    def name(self) -> str:
        return "cicd_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect CI/CD providers using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with CI/CD info.
        """
        providers: List[str] = []
        config_files: List[str] = []

        for provider, config in CI_PROVIDERS.items():
            found = False

            # Check for directory-based CI (e.g., .github/workflows)
            if "directory" in config:
                dir_prefix = config["directory"] + "/"
                extensions = config.get("extensions", [".yml", ".yaml"])
                workflow_files = [
                    fp for fp in walker.file_paths
                    if fp.startswith(dir_prefix)
                    and any(fp.endswith(ext) for ext in extensions)
                ]
                if workflow_files:
                    providers.append(provider)
                    config_files.append(config["directory"])
                    found = True

            # Check for file-based CI
            if not found and "files" in config:
                for ci_file in config["files"]:
                    matching_files = [
                        fp for fp in walker.file_paths
                        if fp.endswith("/" + ci_file) or fp == ci_file
                    ]
                    if matching_files:
                        providers.append(provider)
                        config_files.append(ci_file)
                        break

        return DetectorResult(
            success=True,
            data={
                "providers": providers,
                "config_files": config_files,
                "has_ci": len(providers) > 0,
            },
            confidence=0.9 if providers else 0.0,
        )


# Legacy function interface for backward compatibility
def detect_ci(repo_path: str) -> Optional[CIInfo]:
    """Detect CI/CD in a repository (legacy interface)."""
    import asyncio
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = CICDDetector()
        result = await detector.detect(walker)
        data = result.data
        if not data.get("providers"):
            return None
        return CIInfo(
            provider=data["providers"][0],
            config_file=data["config_files"][0] if data.get("config_files") else "",
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
