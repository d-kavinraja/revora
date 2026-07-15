"""Tests for Intelligence Engine and detectors."""

import pytest
import asyncio
from app.intelligence.engine import IntelligenceEngine
from app.intelligence.repo_walker import RepoWalker
from app.intelligence.language_detector import LanguageDetector
from app.intelligence.framework_detector import FrameworkDetector
from app.intelligence.architecture_detector import ArchitectureDetector
from app.intelligence.database_detector import DatabaseDetector
from app.intelligence.build_detector import BuildDetector
from app.intelligence.cicd_detector import CICDDetector
from app.intelligence.testing_detector import TestingDetector
from app.intelligence.security_detector import SecurityDetector
from app.intelligence.cloud_detector import CloudDetector
from app.intelligence.queue_detector import QueueDetector
from app.intelligence.dependency_analyzer import DependencyAnalyzer
from app.intelligence.secret_detector import SecretDetector
from app.intelligence.complexity_analyzer import ComplexityAnalyzer
from app.intelligence.health_engine import HealthEngine
from app.intelligence.metrics_engine import MetricsEngine


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repository structure for testing."""
    # Create Python files
    (tmp_path / "main.py").write_text("""
import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def index():
    return 'hello'

if __name__ == '__main__':
    app.run()
""")

    # Create requirements.txt
    (tmp_path / "requirements.txt").write_text("flask==2.0.0\nsqlalchemy==1.4.0")

    # Create package.json
    (tmp_path / "package.json").write_text('{"name": "test", "dependencies": {"react": "^18.0.0"}}')

    # Create Dockerfile
    (tmp_path / "Dockerfile").write_text("FROM python:3.9\nCOPY . .")

    # Create docker-compose.yml
    (tmp_path / "docker-compose.yml").write_text("version: '3.8'\nservices:\n  web:\n    build: .")

    # Create GitHub Actions workflow
    gh_dir = tmp_path / ".github" / "workflows"
    gh_dir.mkdir(parents=True)
    (gh_dir / "ci.yml").write_text("name: CI\non: push")

    # Create test directory
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_main.py").write_text("def test_index(): assert True")

    # Create src directory
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("class App: pass")
    (src_dir / "models").mkdir()
    (src_dir / "models" / "user.py").write_text("class User: pass")
    (src_dir / "views").mkdir()
    (src_dir / "views" / "index.py").write_text("def index(): pass")
    (src_dir / "controllers").mkdir()
    (src_dir / "controllers" / "main.py").write_text("def main(): pass")
    (src_dir / "services").mkdir()
    (src_dir / "services" / "auth.py").write_text("def auth(): pass")
    (src_dir / "repositories").mkdir()
    (src_dir / "repositories" / "user.py").write_text("def get_user(): pass")

    # Create .env file
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://localhost/test\nREDIS_URL=redis://localhost")

    # Create secret in code (for secret detector test)
    (tmp_path / "config.py").write_text('API_KEY = "sk-1234567890abcdef1234567890abcdef"')

    return tmp_path


@pytest.mark.asyncio
async def test_intelligence_engine_full(temp_repo):
    """Test full intelligence analysis."""
    engine = IntelligenceEngine()
    result = await engine.analyze(str(temp_repo))

    # Should detect languages
    assert len(result.languages) > 0
    lang_names = [l.name for l in result.languages]
    assert "Python" in lang_names

    # Should have confidence
    assert result.confidence > 0


@pytest.mark.asyncio
async def test_language_detector(temp_repo):
    """Test language detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = LanguageDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert "languages" in result.data
    assert len(result.data["languages"]) > 0


@pytest.mark.asyncio
async def test_framework_detector(temp_repo):
    """Test framework detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = FrameworkDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert "frameworks" in result.data
    # Should detect Flask from requirements.txt
    framework_names = [f.name for f in result.data["frameworks"]]
    assert "Flask" in framework_names


@pytest.mark.asyncio
async def test_architecture_detector(temp_repo):
    """Test architecture detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = ArchitectureDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert "pattern" in result.data
    # Should detect layered architecture (controllers, services, repositories, models)
    assert result.data["pattern"] == "layered"


@pytest.mark.asyncio
async def test_database_detector(temp_repo):
    """Test database detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = DatabaseDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert "databases" in result.data
    # Should detect postgresql from requirements.txt and .env
    assert "postgresql" in result.data["databases"]


@pytest.mark.asyncio
async def test_build_detector(temp_repo):
    """Test build tool detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = BuildDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert "tools" in result.data
    assert result.data["has_docker"] is True
    assert result.data["has_docker_compose"] is True


@pytest.mark.asyncio
async def test_cicd_detector(temp_repo):
    """Test CI/CD detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = CICDDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert "providers" in result.data
    assert "github_actions" in result.data["providers"]


@pytest.mark.asyncio
async def test_testing_detector(temp_repo):
    """Test testing framework detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = TestingDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert result.data["has_tests"] is True
    assert result.data["test_count"] >= 1


@pytest.mark.asyncio
async def test_security_detector(temp_repo):
    """Test security pattern detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = SecurityDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert "auth_patterns" in result.data


@pytest.mark.asyncio
async def test_cloud_detector(temp_repo):
    """Test cloud provider detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = CloudDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert "provider" in result.data


@pytest.mark.asyncio
async def test_queue_detector(temp_repo):
    """Test queue/cache detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = QueueDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert "queues" in result.data
    assert "caching" in result.data


@pytest.mark.asyncio
async def test_dependency_analyzer(temp_repo):
    """Test dependency analysis."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = DependencyAnalyzer()
    result = await detector.detect(walker)

    assert result.success is True
    assert "name" in result.data
    # Should detect pip from requirements.txt
    assert result.data["name"] == "pip"


@pytest.mark.asyncio
async def test_secret_detector(temp_repo):
    """Test secret detection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = SecretDetector()
    result = await detector.detect(walker)

    assert result.success is True
    assert "findings" in result.data
    # Should detect the API key in config.py
    assert result.data["findings_count"] > 0


@pytest.mark.asyncio
async def test_complexity_analyzer(temp_repo):
    """Test complexity analysis."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = ComplexityAnalyzer()
    result = await detector.detect(walker)

    assert result.success is True
    assert "files_analyzed" in result.data
    assert result.data["files_analyzed"] > 0


@pytest.mark.asyncio
async def test_health_engine(temp_repo):
    """Test health scoring."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = HealthEngine()
    result = await detector.detect(walker)

    assert result.success is True
    assert "score" in result.data
    assert "grade" in result.data
    assert 0 <= result.data["score"] <= 1


@pytest.mark.asyncio
async def test_metrics_engine(temp_repo):
    """Test metrics collection."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    detector = MetricsEngine()
    result = await detector.detect(walker)

    assert result.success is True
    assert "total_files" in result.data
    assert result.data["total_files"] > 0
    assert "language_distribution" in result.data


@pytest.mark.asyncio
async def test_detector_error_handling(temp_repo):
    """Test that detector errors are caught gracefully."""
    walker = RepoWalker(str(temp_repo))
    await walker.walk()

    # All detectors should handle errors gracefully
    engine = IntelligenceEngine()
    results = await engine._run_detectors_parallel(walker)

    # All results should be DetectorResult instances
    assert all(hasattr(r, "success") for r in results)
    assert all(hasattr(r, "data") for r in results)


@pytest.mark.asyncio
async def test_intelligence_engine_parallel_execution(temp_repo):
    """Test that detectors run in parallel."""
    import time

    engine = IntelligenceEngine()
    start = time.time()
    result = await engine.analyze(str(temp_repo))
    elapsed = time.time() - start

    # Should complete in reasonable time (parallel execution)
    assert elapsed < 10  # Should be fast with parallel execution
    assert result.confidence > 0
