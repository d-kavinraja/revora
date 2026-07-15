"""Repository health scoring engine.

Calculates an overall health score for the repository based on
multiple factors: testing, documentation, structure, etc.
"""

from typing import Dict

from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.core.constants import (
    HEALTH_WEIGHT_LANGUAGE,
    HEALTH_WEIGHT_FRAMEWORK,
    HEALTH_WEIGHT_ARCHITECTURE,
    HEALTH_WEIGHT_TESTING,
    HEALTH_WEIGHT_SECURITY,
    HEALTH_WEIGHT_DOCUMENTATION,
)


class HealthEngine(BaseDetector):
    """Calculates repository health score."""

    @property
    def name(self) -> str:
        return "health_engine"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Calculate repository health score.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with health score and breakdown.
        """
        scores: Dict[str, float] = {}

        # Language diversity score (0-1)
        languages = walker.get_language_distribution()
        lang_count = len(languages)
        scores["language"] = min(1.0, lang_count * 0.2)

        # Framework score (0-1) - having frameworks is good
        framework_files = [
            fp for fp in walker.file_paths
            if any(fp.endswith(ext) for ext in [
                "package.json", "requirements.txt", "pyproject.toml",
                "go.mod", "Cargo.toml", "Gemfile",
            ])
        ]
        scores["framework"] = min(1.0, len(framework_files) * 0.5)

        # Architecture score (0-1)
        has_structure = any(
            fp.endswith("/") or "/" in fp
            for fp in walker.file_paths
            if "/src/" in fp or "/app/" in fp or "/lib/" in fp
        )
        scores["architecture"] = 0.7 if has_structure else 0.3

        # Testing score (0-1)
        test_files = [
            fp for fp in walker.file_paths
            if "test" in fp.lower() or "spec" in fp.lower()
        ]
        test_configs = [
            fp for fp in walker.file_paths
            if any(fp.endswith(ext) for ext in [
                "jest.config.js", "jest.config.ts",
                "vitest.config.js", "vitest.config.ts",
                "pytest.ini", "conftest.py",
            ])
        ]
        scores["testing"] = min(1.0, (len(test_files) * 0.1 + len(test_configs) * 0.3))

        # Security score (0-1)
        security_files = [
            fp for fp in walker.file_paths
            if any(name in fp.lower() for name in [
                "security", "auth", "permission", "access",
            ])
        ]
        scores["security"] = min(1.0, len(security_files) * 0.3)

        # Documentation score (0-1)
        doc_files = [
            fp for fp in walker.file_paths
            if fp.endswith((".md", ".rst", ".txt"))
            or fp.endswith("README")
            or fp.endswith("CONTRIBUTING")
            or fp.endswith("LICENSE")
        ]
        scores["documentation"] = min(1.0, len(doc_files) * 0.3)

        # Calculate weighted total
        total_score = (
            scores.get("language", 0) * HEALTH_WEIGHT_LANGUAGE
            + scores.get("framework", 0) * HEALTH_WEIGHT_FRAMEWORK
            + scores.get("architecture", 0) * HEALTH_WEIGHT_ARCHITECTURE
            + scores.get("testing", 0) * HEALTH_WEIGHT_TESTING
            + scores.get("security", 0) * HEALTH_WEIGHT_SECURITY
            + scores.get("documentation", 0) * HEALTH_WEIGHT_DOCUMENTATION
        )

        # Determine grade
        if total_score >= 0.8:
            grade = "A"
        elif total_score >= 0.6:
            grade = "B"
        elif total_score >= 0.4:
            grade = "C"
        elif total_score >= 0.2:
            grade = "D"
        else:
            grade = "F"

        return DetectorResult(
            success=True,
            data={
                "score": round(total_score, 2),
                "grade": grade,
                "breakdown": scores,
                "recommendations": self._get_recommendations(scores),
            },
            confidence=0.7,
        )

    def _get_recommendations(self, scores: Dict[str, float]) -> list:
        """Generate recommendations based on scores."""
        recommendations = []

        if scores.get("testing", 0) < 0.3:
            recommendations.append("Add test files and configure a test framework")
        if scores.get("documentation", 0) < 0.3:
            recommendations.append("Add README, CONTRIBUTING, and LICENSE files")
        if scores.get("security", 0) < 0.3:
            recommendations.append("Add security-related files and configurations")
        if scores.get("architecture", 0) < 0.5:
            recommendations.append("Organize code into src/ or app/ directories")

        return recommendations
