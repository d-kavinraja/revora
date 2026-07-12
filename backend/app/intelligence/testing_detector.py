import os
from typing import Optional

from app.intelligence.models import TestingInfo

TEST_FRAMEWORKS = {
    "jest": ["jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.json"],
    "vitest": ["vitest.config.js", "vitest.config.ts", "vitest.config.mjs"],
    "mocha": [".mocharc.yml", ".mocharc.js", ".mocharc.json"],
    "pytest": ["pytest.ini", "conftest.py", "pyproject.toml"],
    "unittest": ["test_*.py", "*_test.py"],
    "go test": ["*_test.go"],
    "rspec": [".rspec", "spec/"],
    "phpunit": ["phpunit.xml", "phpunit.xml.dist"],
    "xunit": ["*.csproj"],
}

TEST_DIRS = {
    "tests", "test", "__tests__", "spec", "e2e", "integration",
    "src/tests", "src/test", "tests/unit", "tests/integration",
}


def detect_testing(repo_path: str) -> TestingInfo:
    framework: Optional[str] = None
    has_tests = False
    test_count = 0
    test_dirs: list[str] = []

    for fw_name, markers in TEST_FRAMEWORKS.items():
        for marker in markers:
            if os.path.exists(os.path.join(repo_path, marker)):
                framework = fw_name
                break
            if os.path.isdir(os.path.join(repo_path, marker)):
                framework = fw_name
                break
        if framework:
            break

    for test_dir in TEST_DIRS:
        full_path = os.path.join(repo_path, test_dir)
        if os.path.isdir(full_path):
            test_dirs.append(test_dir)
            has_tests = True
            for root, dirs, files in os.walk(full_path):
                dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__"}]
                for f in files:
                    if f.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java")):
                        test_count += 1

    if not has_tests:
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__"}]
            for f in files:
                if f.startswith("test_") or f.endswith("_test.py") or f.endswith(".test.js") or f.endswith(".test.ts") or f.endswith("_test.go"):
                    has_tests = True
                    test_count += 1
            if has_tests:
                break

    return TestingInfo(
        framework=framework,
        has_tests=has_tests,
        test_count=test_count,
        test_directories=test_dirs,
    )
