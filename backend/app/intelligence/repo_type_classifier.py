import os
import json
from typing import Optional


def classify_repo_type(repo_path: str) -> str:
    top_level = set()
    for item in os.listdir(repo_path):
        full = os.path.join(repo_path, item)
        if os.path.isdir(full) and not item.startswith("."):
            top_level.add(item.lower())

    package_json_path = os.path.join(repo_path, "package.json")
    has_workspaces = False
    if os.path.exists(package_json_path):
        try:
            with open(package_json_path, "r") as f:
                pkg = json.load(f)
            if "workspaces" in pkg:
                has_workspaces = True
        except (json.JSONDecodeError, OSError):
            pass

    if has_workspaces or "packages" in top_level or "apps" in top_level:
        return "monorepo"

    if "services" in top_level or "microservices" in top_level:
        service_dir = os.path.join(repo_path, "services") if "services" in top_level else os.path.join(repo_path, "microservices")
        if os.path.isdir(service_dir):
            sub_count = len([d for d in os.listdir(service_dir) if os.path.isdir(os.path.join(service_dir, d))])
            if sub_count >= 2:
                return "microservices"

    domain_dir = os.path.join(repo_path, "domain")
    infra_dir = os.path.join(repo_path, "infrastructure")
    if os.path.isdir(domain_dir) and os.path.isdir(infra_dir):
        return "ddd"

    if "src" in top_level:
        src_items = set()
        src_path = os.path.join(repo_path, "src")
        for item in os.listdir(src_path):
            if os.path.isdir(os.path.join(src_path, item)):
                src_items.add(item.lower())

        if {"entities", "usecases", "adapters"} <= src_items:
            return "clean_architecture"
        if {"domain", "ports", "adapters"} <= src_items:
            return "hexagonal"
        if {"models", "views", "controllers"} <= src_items:
            return "mvc"
        if {"controllers", "services", "repositories", "models"} <= src_items:
            return "layered"

    return "standard"
