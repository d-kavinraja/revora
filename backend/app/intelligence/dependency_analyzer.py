import os
import json
from typing import Optional, Tuple

from app.intelligence.models import PackageManagerInfo


def detect_package_manager(repo_path: str) -> Optional[PackageManagerInfo]:
    lock_files = {
        "package-lock.json": "npm",
        "yarn.lock": "yarn",
        "pnpm-lock.yaml": "pnpm",
        "poetry.lock": "poetry",
        "Pipfile.lock": "pipenv",
        "uv.lock": "uv",
        "Cargo.lock": "cargo",
        "go.sum": "go",
        "Gemfile.lock": "bundler",
        "composer.lock": "composer",
    }

    config_files = {
        "package.json": "npm",
        "pyproject.toml": "python",
        "Cargo.toml": "cargo",
        "go.mod": "go",
        "Gemfile": "bundler",
        "composer.json": "composer",
        "build.gradle": "gradle",
        "build.gradle.kts": "gradle",
        "pom.xml": "maven",
    }

    for lock_file, manager in lock_files.items():
        if os.path.exists(os.path.join(repo_path, lock_file)):
            config = config_files.get(lock_file.replace("lock", "json").replace("-lock", ""), lock_file)
            return PackageManagerInfo(name=manager, lock_file=lock_file, config_file=config)

    for config_file, manager in config_files.items():
        if os.path.exists(os.path.join(repo_path, config_file)):
            return PackageManagerInfo(name=manager, config_file=config_file)

    return None


def count_dependencies(repo_path: str, package_manager: Optional[PackageManagerInfo]) -> int:
    if not package_manager:
        return 0

    count = 0

    if package_manager.name == "npm" and package_manager.config_file:
        pkg_path = os.path.join(repo_path, "package.json")
        try:
            with open(pkg_path, "r") as f:
                pkg = json.load(f)
            count = len(pkg.get("dependencies", {})) + len(pkg.get("devDependencies", {}))
        except (json.JSONDecodeError, OSError):
            pass

    elif package_manager.name in ("poetry", "uv") and os.path.exists(os.path.join(repo_path, "pyproject.toml")):
        try:
            with open(os.path.join(repo_path, "pyproject.toml"), "r") as f:
                content = f.read()
            count = content.count("\n") // 2  # rough estimate
        except OSError:
            pass

    elif package_manager.name == "cargo":
        cargo_path = os.path.join(repo_path, "Cargo.toml")
        try:
            with open(cargo_path, "r") as f:
                content = f.read()
            count = content.count('"') // 2
        except OSError:
            pass

    return count
