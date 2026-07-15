"""Framework detection engine.

Detects frameworks by checking config file existence and content.
Uses the shared RepoWalker for efficient filesystem access.
"""

import os
from typing import List, Optional, Tuple

from app.intelligence.models import FrameworkInfo
from app.intelligence.base_detector import BaseDetector, DetectorResult


# Framework signatures: (name, signatures, config_file)
FRAMEWORK_SIGNATURES: List[Tuple[str, List[str], Optional[str]]] = [
    # JavaScript / TypeScript
    ("Next.js", ["next.config.js", "next.config.ts", "next.config.mjs"], None),
    ("React", ["react", "react-dom"], "package.json"),
    ("Vue.js", ["vue", "nuxt"], "package.json"),
    ("Nuxt", ["nuxt.config.js", "nuxt.config.ts"], None),
    ("Svelte", ["svelte", "@sveltejs/kit"], "package.json"),
    ("Angular", ["@angular/core"], "package.json"),
    ("Express.js", ["express"], "package.json"),
    ("Fastify", ["fastify"], "package.json"),
    ("NestJS", ["@nestjs/core"], "package.json"),
    ("Remix", ["@remix-run/react"], "package.json"),
    ("Vite", ["vite"], "package.json"),
    ("Webpack", ["webpack"], "package.json"),

    # Python
    ("FastAPI", ["fastapi"], "requirements.txt"),
    ("FastAPI", ["fastapi"], "pyproject.toml"),
    ("Django", ["django"], "requirements.txt"),
    ("Django", ["django"], "pyproject.toml"),
    ("Flask", ["flask"], "requirements.txt"),
    ("Flask", ["flask"], "pyproject.toml"),
    ("Starlette", ["starlette"], "requirements.txt"),
    ("Celery", ["celery"], "requirements.txt"),
    ("Celery", ["celery"], "pyproject.toml"),

    # Go
    ("Gin", ["github.com/gin-gonic/gin"], "go.mod"),
    ("Echo", ["github.com/labstack/echo"], "go.mod"),
    ("Fiber", ["github.com/gofiber/fiber"], "go.mod"),
    ("Chi", ["github.com/go-chi/chi"], "go.mod"),

    # Java / Kotlin
    ("Spring Boot", ["org.springframework.boot"], "pom.xml"),
    ("Spring Boot", ["org.springframework.boot"], "build.gradle"),
    ("Micronaut", ["io.micronaut"], "build.gradle"),

    # Rust
    ("Actix Web", ["actix-web"], "Cargo.toml"),
    ("Axum", ["axum"], "Cargo.toml"),
    ("Rocket", ["rocket"], "Cargo.toml"),

    # Ruby
    ("Rails", ["rails"], "Gemfile"),
    ("Sinatra", ["sinatra"], "Gemfile"),
]


class FrameworkDetector(BaseDetector):
    """Detects frameworks by checking config file existence and content."""

    @property
    def name(self) -> str:
        return "framework_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect frameworks using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with detected frameworks.
        """
        frameworks: List[FrameworkInfo] = []
        seen = set()

        for name, signatures, config_file in FRAMEWORK_SIGNATURES:
            if name in seen:
                continue

            if config_file:
                # Check if config file exists via walker
                config_files = [
                    fp for fp in walker.file_paths
                    if fp.endswith(config_file) or fp.endswith("/" + config_file)
                ]

                if not config_files:
                    continue

                # Read config file content
                content = await walker.get_content(config_files[0])
                if any(sig in content for sig in signatures):
                    frameworks.append(
                        FrameworkInfo(name=name, config_file=config_file)
                    )
                    seen.add(name)
            else:
                # Check for config file existence
                for sig in signatures:
                    matching_files = [
                        fp for fp in walker.file_paths
                        if fp.endswith("/" + sig) or fp == sig
                    ]
                    if matching_files:
                        frameworks.append(
                            FrameworkInfo(name=name, config_file=sig)
                        )
                        seen.add(name)
                        break

        return DetectorResult(
            success=True,
            data={
                "frameworks": frameworks,
                "framework_count": len(frameworks),
            },
            confidence=min(1.0, len(frameworks) * 0.3),
        )


# Legacy function interface for backward compatibility
def detect_frameworks(repo_path: str) -> List[FrameworkInfo]:
    """Detect frameworks in a repository (legacy interface).

    Args:
        repo_path: Path to repository root.

    Returns:
        List of FrameworkInfo objects.
    """
    import asyncio
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = FrameworkDetector()
        result = await detector.detect(walker)
        return result.data.get("frameworks", [])

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
