"""Repository Intelligence Engine.

Analyzes a repository to extract structural intelligence without using LLM.
All analysis is deterministic and runs before any LLM invocation.
"""

import time
import logging
import asyncio
from typing import Optional, List

from app.intelligence.models import IntelligenceResult
from app.intelligence.repo_walker import RepoWalker
from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.intelligence.language_detector import LanguageDetector
from app.intelligence.framework_detector import FrameworkDetector
from app.intelligence.architecture_detector import ArchitectureDetector
from app.intelligence.database_detector import DatabaseDetector
from app.intelligence.dependency_analyzer import DependencyAnalyzer
from app.intelligence.testing_detector import TestingDetector
from app.intelligence.build_detector import BuildDetector
from app.intelligence.cicd_detector import CICDDetector
from app.intelligence.security_detector import SecurityDetector
from app.intelligence.cloud_detector import CloudDetector
from app.intelligence.queue_detector import QueueDetector

logger = logging.getLogger(__name__)


class IntelligenceEngine:
    """Analyzes a repository to extract structural intelligence.

    Runs all detectors in parallel with per-detector error handling.
    A single detector failure does not affect other detectors.
    """

    def __init__(self):
        self._detectors: List[BaseDetector] = [
            LanguageDetector(),
            FrameworkDetector(),
            ArchitectureDetector(),
            DatabaseDetector(),
            DependencyAnalyzer(),
            TestingDetector(),
            BuildDetector(),
            CICDDetector(),
            SecurityDetector(),
            CloudDetector(),
            QueueDetector(),
        ]

    def register_detector(self, detector: BaseDetector) -> None:
        """Register a new detector.

        Args:
            detector: Detector instance implementing BaseDetector.
        """
        self._detectors.append(detector)
        logger.info(f"Registered detector: {detector.name}")

    async def analyze(
        self,
        repo_path: str,
        walker: Optional[RepoWalker] = None,
    ) -> IntelligenceResult:
        """Run all detectors on the repository.

        Args:
            repo_path: Path to repository root.
            walker: Optional pre-initialized RepoWalker.

        Returns:
            IntelligenceResult with data from all successful detectors.
        """
        start = time.time()
        logger.info(f"Starting repository intelligence analysis for: {repo_path}")

        # Initialize walker if not provided
        if walker is None:
            walker = RepoWalker(repo_path)
            await walker.walk()

        # Run all detectors in parallel with error isolation
        results = await self._run_detectors_parallel(walker)

        # Build result from successful detections
        result = self._build_result(results)

        elapsed_ms = (time.time() - start) * 1000
        logger.info(
            f"Intelligence analysis completed in {elapsed_ms:.0f}ms "
            f"({len([r for r in results if r.success])}/{len(results)} "
            f"detectors succeeded)"
        )

        return result

    async def _run_detectors_parallel(
        self,
        walker: RepoWalker,
    ) -> List[DetectorResult]:
        """Run all detectors in parallel with error isolation.

        Each detector runs independently. A failure in one detector
        does not affect others.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            List of DetectorResults from all detectors.
        """
        tasks = [detector.safe_detect(walker) for detector in self._detectors]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"Detector {self._detectors[i].name} raised exception: {result}"
                )
                final_results.append(
                    DetectorResult(
                        success=False,
                        data={},
                        error=str(result),
                        detector_name=self._detectors[i].name,
                    )
                )
            else:
                final_results.append(result)

        return final_results

    def _build_result(self, results: List[DetectorResult]) -> IntelligenceResult:
        """Build IntelligenceResult from detector results.

        Args:
            results: List of DetectorResults.

        Returns:
            Combined IntelligenceResult.
        """
        # Map detector names to result data
        data_map = {}
        for result in results:
            if result.success and result.data:
                data_map[result.detector_name] = result.data

        # Extract data from each detector
        languages = data_map.get("language_detector", {}).get("languages", [])
        frameworks = data_map.get("framework_detector", {}).get("frameworks", [])
        architecture_data = data_map.get("architecture_detector", {})
        database_data = data_map.get("database_detector", {})
        package_data = data_map.get("dependency_analyzer", {})
        testing_data = data_map.get("testing_detector", {})
        build_data = data_map.get("build_detector", {})
        ci_data = data_map.get("cicd_detector", {})
        security_data = data_map.get("security_detector", {})
        cloud_data = data_map.get("cloud_detector", {})
        queue_data = data_map.get("queue_detector", {})

        # Build architecture info
        from app.intelligence.models import ArchitectureInfo, DatabaseInfo, TestingInfo, BuildInfo, SecurityInfo

        architecture = ArchitectureInfo(
            pattern=architecture_data.get("pattern", "standard"),
            confidence=architecture_data.get("confidence", 0.5),
            indicators=architecture_data.get("indicators", []),
        )

        database = DatabaseInfo(
            type=database_data.get("databases", [None])[0] if database_data.get("databases") else None,
            orm=database_data.get("orms", [None])[0] if database_data.get("orms") else None,
            indicators=database_data.get("indicators", []),
        )

        testing = TestingInfo(
            framework=testing_data.get("framework"),
            has_tests=testing_data.get("has_tests", False),
            test_count=testing_data.get("test_count", 0),
            test_directories=testing_data.get("test_directories", []),
        )

        build = BuildInfo(
            tools=build_data.get("tools", []),
            dockerfile=build_data.get("has_docker", False),
            docker_compose=build_data.get("has_docker_compose", False),
        )

        security = SecurityInfo(
            auth_patterns=security_data.get("auth_patterns", []),
            has_cors=security_data.get("has_cors", False),
            has_rate_limiting=security_data.get("has_rate_limiting", False),
            has_https_redirect=security_data.get("has_https_redirect", False),
        )

        from app.intelligence.models import PackageManagerInfo, CIInfo

        package_manager = PackageManagerInfo(
            name=package_data.get("name", ""),
            lock_file=package_data.get("lock_file", ""),
        )

        ci = CIInfo(
            provider=ci_data.get("providers", [None])[0] if ci_data.get("providers") else None,
            config_file=ci_data.get("config_files", [None])[0] if ci_data.get("config_files") else None,
        )

        return IntelligenceResult(
            languages=languages,
            frameworks=frameworks,
            architecture=architecture,
            database=database,
            package_manager=package_manager,
            testing=testing,
            build=build,
            ci=ci,
            security=security,
            repo_type=architecture_data.get("repo_type", "standard"),
            cloud_provider=cloud_data.get("provider", ""),
            caching=queue_data.get("caching", []),
            queues=queue_data.get("queues", []),
            confidence=self._calculate_confidence(languages, frameworks, architecture),
        )

    def _calculate_confidence(self, languages, frameworks, architecture) -> float:
        """Calculate overall confidence score for the analysis.

        Args:
            languages: Detected languages.
            frameworks: Detected frameworks.
            architecture: Architecture info.

        Returns:
            Confidence score between 0.0 and 1.0.
        """
        score = 0.3
        if languages:
            score += 0.2
        if frameworks:
            score += 0.2
        if architecture and architecture.confidence > 0.5:
            score += 0.2
        if len(languages) > 1:
            score += 0.1
        return min(score, 1.0)


intelligence_engine = IntelligenceEngine()
