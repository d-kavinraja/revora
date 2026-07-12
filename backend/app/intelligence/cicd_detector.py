import os
from typing import Optional, List

from app.intelligence.models import CIInfo


CI_PROVIDERS = {
    "github_actions": {
        "directory": ".github/workflows",
        "extensions": [".yml", ".yaml"],
    },
    "gitlab_ci": {
        "files": [".gitlab-ci.yml"],
    },
    "circleci": {
        "directory": ".circleci",
        "files": ["config.yml"],
    },
    "jenkins": {
        "files": ["Jenkinsfile"],
    },
    "travis_ci": {
        "files": [".travis.yml"],
    },
    "azure_pipelines": {
        "files": ["azure-pipelines.yml"],
    },
    "bitbucket": {
        "files": ["bitbucket-pipelines.yml"],
    },
    "drone": {
        "files": [".drone.yml"],
    },
}


def detect_ci(repo_path: str) -> Optional[CIInfo]:
    for provider, config in CI_PROVIDERS.items():
        if "directory" in config:
            workflow_dir = os.path.join(repo_path, config["directory"])
            if os.path.isdir(workflow_dir):
                workflows = []
                for f in os.listdir(workflow_dir):
                    if f.endswith(config.get("extensions", [".yml", ".yaml"])):
                        workflows.append(f)
                if workflows:
                    return CIInfo(
                        provider=provider,
                        config_file=config["directory"],
                        workflows=workflows,
                    )

        if "files" in config:
            for f in config["files"]:
                if os.path.exists(os.path.join(repo_path, f)):
                    return CIInfo(provider=provider, config_file=f)

    return None
