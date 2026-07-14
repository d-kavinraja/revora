"""Architecture detection engine.

Detects architectural patterns (DDD, Clean, Hexagonal, MVC, etc.)
and repository type (monorepo, microservices) from directory structure.
Uses the shared RepoWalker for efficient filesystem access.
"""

import json
from typing import List, Set

from app.intelligence.models import ArchitectureInfo
from app.intelligence.base_detector import BaseDetector, DetectorResult


class ArchitectureDetector(BaseDetector):
    """Detects architectural patterns and repository type."""

    @property
    def name(self) -> str:
        return "architecture_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect architecture using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with architecture info and repo type.
        """
        indicators: List[str] = []
        scores = {}

        # Collect all directory names from file paths
        all_dirs: Set[str] = set()
        for fp in walker.file_paths:
            parts = fp.replace("\\", "/").split("/")
            for part in parts[:-1]:  # Skip filename
                all_dirs.add(part.lower())

        # DDD patterns
        ddd_markers = {"domain", "application", "infrastructure", "presentation"}
        found_ddd = ddd_markers & all_dirs
        if len(found_ddd) >= 2:
            scores["ddd"] = 0.9
            indicators.append(f"DDD directories found: {found_ddd}")

        # Clean Architecture
        clean_markers = {"entities", "usecases", "adapters", "frameworks", "interfaces"}
        found_clean = clean_markers & all_dirs
        if len(found_clean) >= 2:
            scores["clean"] = 0.85
            indicators.append(f"Clean Architecture directories: {found_clean}")

        # Hexagonal Architecture
        hex_markers = {"domain", "ports", "adapters"}
        found_hex = hex_markers & all_dirs
        if len(found_hex) >= 2:
            scores["hexagonal"] = 0.8
            indicators.append(f"Hexagonal Architecture markers: {found_hex}")

        # Layered Architecture
        layer_markers = {"controllers", "services", "repositories", "models"}
        found_layered = layer_markers & all_dirs
        if len(found_layered) >= 2:
            scores["layered"] = 0.75
            indicators.append(f"Layered Architecture directories: {found_layered}")

        # MVC
        mvc_markers = {"models", "views", "controllers"}
        found_mvc = mvc_markers & all_dirs
        if len(found_mvc) >= 2:
            scores["mvc"] = 0.7
            indicators.append(f"MVC directories: {found_mvc}")

        # Microservices detection
        has_services = "services" in all_dirs or "microservices" in all_dirs
        if has_services:
            service_files = [
                fp for fp in walker.file_paths
                if "/services/" in fp or "/microservices/" in fp
            ]
            # Count unique service directories
            service_dirs = set()
            for fp in service_files:
                parts = fp.replace("\\", "/").split("/")
                for i, part in enumerate(parts):
                    if part in ("services", "microservices") and i + 1 < len(parts) - 1:
                        service_dirs.add(parts[i + 1])
            if len(service_dirs) >= 2:
                scores["microservices"] = 0.8
                indicators.append(f"Multiple service directories: {service_dirs}")

        # Monorepo detection
        has_workspaces = False
        package_json_files = [
            fp for fp in walker.file_paths if fp.endswith("package.json")
        ]
        for pj_file in package_json_files:
            content = await walker.get_content(pj_file, max_chars=5000)
            try:
                pkg = json.loads(content)
                if "workspaces" in pkg:
                    has_workspaces = True
                    indicators.append("npm/yarn workspaces detected")
                    break
            except (json.JSONDecodeError, ValueError):
                continue

        has_packages_dir = "packages" in all_dirs
        has_apps_dir = "apps" in all_dirs

        if has_workspaces or has_packages_dir or has_apps_dir:
            scores["monorepo"] = 0.85
            if not any("monorepo" in ind for ind in indicators):
                indicators.append("Monorepo structure detected")

        # Select best match
        if scores:
            best_pattern = max(scores, key=scores.get)
            repo_type = best_pattern
        else:
            best_pattern = "standard"
            repo_type = "standard"
            indicators.append("No specific architecture pattern detected")

        return DetectorResult(
            success=True,
            data={
                "pattern": best_pattern,
                "confidence": scores.get(best_pattern, 0.5),
                "indicators": indicators,
                "repo_type": repo_type,
                "all_scores": scores,
            },
            confidence=scores.get(best_pattern, 0.5),
        )


# Legacy function interface for backward compatibility
def detect_architecture(repo_path: str) -> ArchitectureInfo:
    """Detect architecture in a repository (legacy interface).

    Args:
        repo_path: Path to repository root.

    Returns:
        ArchitectureInfo object.
    """
    import asyncio
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = ArchitectureDetector()
        result = await detector.detect(walker)
        data = result.data
        return ArchitectureInfo(
            pattern=data.get("pattern", "standard"),
            confidence=data.get("confidence", 0.5),
            indicators=data.get("indicators", []),
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
