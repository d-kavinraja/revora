import os
from typing import List

from app.intelligence.models import ArchitectureInfo


def detect_architecture(repo_path: str) -> ArchitectureInfo:
    indicators: list[str] = []
    scores: dict[str, float] = {}

    top_level = set()
    for item in os.listdir(repo_path):
        if os.path.isdir(os.path.join(repo_path, item)) and not item.startswith("."):
            top_level.add(item.lower())

    src_contents = set()
    src_path = os.path.join(repo_path, "src")
    if os.path.isdir(src_path):
        for item in os.listdir(src_path):
            if os.path.isdir(os.path.join(src_path, item)):
                src_contents.add(item.lower())

    app_path = os.path.join(repo_path, "app")
    app_contents = set()
    if os.path.isdir(app_path):
        for item in os.listdir(app_path):
            if os.path.isdir(os.path.join(app_path, item)):
                app_contents.add(item.lower())

    all_dirs = top_level | src_contents | app_contents

    # DDD patterns
    ddd_markers = {"domain", "application", "infrastructure", "presentation"}
    if len(ddd_markers & all_dirs) >= 2:
        scores["ddd"] = 0.9
        indicators.append(f"DDD directories found: {ddd_markers & all_dirs}")

    # Clean Architecture
    clean_markers = {"entities", "usecases", "adapters", "frameworks", "interfaces"}
    if len(clean_markers & all_dirs) >= 2:
        scores["clean"] = 0.85
        indicators.append(f"Clean Architecture directories: {clean_markers & all_dirs}")

    # Hexagonal Architecture
    hex_markers = {"domain", "ports", "adapters"}
    if len(hex_markers & all_dirs) >= 2:
        scores["hexagonal"] = 0.8
        indicators.append(f"Hexagonal Architecture markers: {hex_markers & all_dirs}")

    # Layered Architecture
    layer_markers = {"controllers", "services", "repositories", "models"}
    if len(layer_markers & all_dirs) >= 2:
        scores["layered"] = 0.75
        indicators.append(f"Layered Architecture directories: {layer_markers & all_dirs}")

    # MVC
    mvc_markers = {"models", "views", "controllers"}
    if len(mvc_markers & all_dirs) >= 2:
        scores["mvc"] = 0.7
        indicators.append(f"MVC directories: {mvc_markers & all_dirs}")

    # Microservices
    services_dir = os.path.join(repo_path, "services")
    packages_dir = os.path.join(repo_path, "packages")
    modules_dir = os.path.join(repo_path, "modules")
    if os.path.isdir(services_dir) or os.path.isdir(packages_dir) or os.path.isdir(modules_dir):
        service_dir = services_dir if os.path.isdir(services_dir) else (packages_dir if os.path.isdir(packages_dir) else modules_dir)
        sub_services = [d for d in os.listdir(service_dir) if os.path.isdir(os.path.join(service_dir, d))]
        if len(sub_services) >= 2:
            scores["microservices"] = 0.8
            indicators.append(f"Multiple service directories: {sub_services}")

    # Monorepo detection
    has_workspaces = False
    package_json = os.path.join(repo_path, "package.json")
    if os.path.exists(package_json):
        try:
            import json
            with open(package_json, "r") as f:
                pkg = json.load(f)
            if "workspaces" in pkg:
                has_workspaces = True
                indicators.append("npm/yarn workspaces detected")
        except (json.JSONDecodeError, OSError):
            pass

    if has_workspaces or os.path.isdir(os.path.join(repo_path, "packages")) or os.path.isdir(os.path.join(repo_path, "apps")):
        scores["monorepo"] = 0.85
        if "monorepo" not in str(indicators):
            indicators.append("Monorepo structure detected")

    # Select best match
    if scores:
        best_pattern = max(scores, key=scores.get)
        return ArchitectureInfo(
            pattern=best_pattern,
            confidence=scores[best_pattern],
            indicators=indicators,
        )

    return ArchitectureInfo(pattern="standard", confidence=0.5, indicators=["No specific architecture pattern detected"])
