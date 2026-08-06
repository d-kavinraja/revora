# ruff: noqa: F821
"""Testing framework detection engine.

Detects test frameworks and counts test files.
Uses the shared RepoWalker for efficient filesystem access.
"""


from app.intelligence._async_util import run_async
from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.intelligence.models import TestingInfo

TEST_FRAMEWORKS = {
    "jest": ["jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.json"],
    "vitest": ["vitest.config.js", "vitest.config.ts", "vitest.config.mjs"],
    "mocha": [".mocharc.yml", ".mocharc.js", ".mocharc.json"],
    "pytest": ["pytest.ini", "conftest.py"],
    "unittest": ["test_*.py", "*_test.py"],
    "go test": ["*_test.go"],
    "rspec": [".rspec"],
    "phpunit": ["phpunit.xml", "phpunit.xml.dist"],
}

TEST_DIRS = {
    "tests",
    "test",
    "__tests__",
    "spec",
    "e2e",
    "integration",
    "src/tests",
    "src/test",
    "tests/unit",
    "tests/integration",
}

TEST_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java"}


class TestingDetector(BaseDetector):
    """Detects test frameworks and counts test files."""

    @property
    def name(self) -> str:
        return "testing_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: "RepoWalker") -> DetectorResult:
        """Detect testing frameworks using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with testing info.
        """
        framework: str | None = None
        has_tests = False
        test_count = 0
        test_dirs: list[str] = []

        # Detect framework from config files
        for fw_name, markers in TEST_FRAMEWORKS.items():
            for marker in markers:
                matching_files = [
                    fp
                    for fp in walker.file_paths
                    if fp.endswith("/" + marker) or fp == marker
                ]
                if matching_files:
                    framework = fw_name
                    break
            if framework:
                break

        # Count test files in known test directories
        for test_dir in TEST_DIRS:
            dir_files = [
                fp
                for fp in walker.file_paths
                if ("/" + test_dir + "/") in fp or fp.startswith(test_dir + "/")
            ]
            if dir_files:
                test_dirs.append(test_dir)
                has_tests = True
                for fp in dir_files:
                    if any(fp.endswith(ext) for ext in TEST_EXTENSIONS):
                        test_count += 1

        # If no test directories found, look for test files in root
        if not has_tests:
            for fp in walker.file_paths:
                filename = fp.split("/")[-1].split("\\")[-1]
                if filename.startswith("test_") or filename.endswith(
                    ("_test.py", ".test.js", ".test.ts", "_test.go")
                ):
                    has_tests = True
                    test_count += 1
                    break

        return DetectorResult(
            success=True,
            data={
                "framework": framework,
                "has_tests": has_tests,
                "test_count": test_count,
                "test_directories": test_dirs,
            },
            confidence=0.9 if framework else (0.7 if has_tests else 0.0),
        )


# Legacy function interface for backward compatibility
def detect_testing(repo_path: str) -> TestingInfo:
    """Detect testing in a repository (legacy interface)."""
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = TestingDetector()
        result = await detector.detect(walker)
        data = result.data
        return TestingInfo(
            framework=data.get("framework"),
            has_tests=data.get("has_tests", False),
            test_count=data.get("test_count", 0),
            test_directories=data.get("test_directories", []),
        )

    return run_async(_detect())
