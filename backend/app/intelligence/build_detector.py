# ruff: noqa: F821
"""Build tool detection engine.

Detects build tools and Docker presence.
Uses the shared RepoWalker for efficient filesystem access.
"""


from app.intelligence._async_util import run_async
from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.intelligence.models import BuildInfo

BUILD_TOOLS = {
    "webpack": ["webpack.config.js", "webpack.config.ts", "webpack.config.mjs"],
    "vite": ["vite.config.js", "vite.config.ts", "vite.config.mjs"],
    "esbuild": ["esbuild.config.js", "esbuild.config.mjs"],
    "rollup": ["rollup.config.js", "rollup.config.ts", "rollup.config.mjs"],
    "turbopack": ["turbo.json"],
    "gradle": ["build.gradle", "build.gradle.kts"],
    "maven": ["pom.xml"],
    "cmake": ["CMakeLists.txt"],
    "make": ["Makefile"],
    "cargo": ["Cargo.toml"],
    "go build": ["go.mod"],
    "mix": ["mix.exs"],
}


class BuildDetector(BaseDetector):
    """Detects build tools and Docker presence."""

    @property
    def name(self) -> str:
        return "build_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: "RepoWalker") -> DetectorResult:
        """Detect build tools using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with build tool info.
        """
        tools: list[str] = []

        # Check for Docker files
        docker_files = [
            fp
            for fp in walker.file_paths
            if fp.lower().endswith("dockerfile")
            or fp.endswith(
                ("docker-compose.yml", "docker-compose.yaml", "docker-compose.json")
            )
        ]
        has_dockerfile = any("dockerfile" in fp.lower() for fp in docker_files)
        has_docker_compose = any("docker-compose" in fp for fp in docker_files)

        # Detect build tools
        for tool_name, config_files in BUILD_TOOLS.items():
            for config_file in config_files:
                matching_files = [
                    fp
                    for fp in walker.file_paths
                    if fp.endswith("/" + config_file) or fp == config_file
                ]
                if matching_files:
                    tools.append(tool_name)
                    break

        return DetectorResult(
            success=True,
            data={
                "tools": tools,
                "has_docker": has_dockerfile,
                "has_docker_compose": has_docker_compose,
                "has_makefile": "make" in tools,
            },
            confidence=0.9 if tools else 0.3,
        )


# Legacy function interface for backward compatibility
def detect_build_tools(repo_path: str) -> BuildInfo:
    """Detect build tools in a repository (legacy interface)."""
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = BuildDetector()
        result = await detector.detect(walker)
        data = result.data
        return BuildInfo(
            tools=data.get("tools", []),
            dockerfile=data.get("has_docker", False),
            docker_compose=data.get("has_docker_compose", False),
        )

    return run_async(_detect())
