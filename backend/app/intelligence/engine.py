import time
import logging
from typing import Optional

from app.intelligence.models import IntelligenceResult
from app.intelligence.language_detector import detect_languages
from app.intelligence.framework_detector import detect_frameworks
from app.intelligence.architecture_detector import detect_architecture
from app.intelligence.dependency_analyzer import detect_package_manager, count_dependencies
from app.intelligence.database_detector import detect_database
from app.intelligence.cicd_detector import detect_ci
from app.intelligence.build_detector import detect_build_tools
from app.intelligence.security_detector import detect_security
from app.intelligence.testing_detector import detect_testing
from app.intelligence.repo_type_classifier import classify_repo_type
from app.intelligence.cloud_detector import detect_cloud_provider
from app.intelligence.queue_detector import detect_queues, detect_caching

logger = logging.getLogger(__name__)


class IntelligenceEngine:
    """Analyzes a repository to extract structural intelligence without using LLM."""

    async def analyze(self, repo_path: str) -> IntelligenceResult:
        start = time.time()
        logger.info(f"Starting repository intelligence analysis for: {repo_path}")

        languages = detect_languages(repo_path)
        frameworks = detect_frameworks(repo_path)
        architecture = detect_architecture(repo_path)
        database = detect_database(repo_path)
        package_manager = detect_package_manager(repo_path)
        testing = detect_testing(repo_path)
        build = detect_build_tools(repo_path)
        ci = detect_ci(repo_path)
        security = detect_security(repo_path)
        repo_type = classify_repo_type(repo_path)
        cloud = detect_cloud_provider(repo_path)
        caching = detect_caching(repo_path)
        queues = detect_queues(repo_path)

        elapsed_ms = (time.time() - start) * 1000
        logger.info(f"Intelligence analysis completed in {elapsed_ms:.0f}ms")

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
            repo_type=repo_type,
            cloud_provider=cloud,
            caching=caching,
            queues=queues,
            confidence=self._calculate_confidence(languages, frameworks, architecture),
        )

    def _calculate_confidence(self, languages, frameworks, architecture) -> float:
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
