import os
from typing import List

from app.intelligence.models import BuildInfo


BUILD_TOOLS = {
    "webpack": ["webpack.config.js", "webpack.config.ts", "webpack.config.mjs"],
    "vite": ["vite.config.js", "vite.config.ts", "vite.config.mjs"],
    "esbuild": ["esbuild.config.js", "esbuild.config.mjs"],
    "rollup": ["rollup.config.js", "rollup.config.ts", "rollup.config.mjs"],
    "turbopack": ["turbo.json"],
    "gradle": ["build.gradle", "build.gradle.kts"],
    "maven": ["pom.xml"],
    "cmake": ["CMakeLists.txt"],
    "make": ["Makefile"],
    "cargo": ["Cargo.toml"],
    "go build": ["go.mod"],
    "mix": ["mix.exs"],
    "msbuild": ["*.csproj", "*.sln"],
}


def detect_build_tools(repo_path: str) -> BuildInfo:
    tools: list[str] = []
    dockerfile = os.path.exists(os.path.join(repo_path, "Dockerfile")) or os.path.exists(os.path.join(repo_path, "dockerfile"))
    docker_compose = os.path.exists(os.path.join(repo_path, "docker-compose.yml")) or os.path.exists(os.path.join(repo_path, "docker-compose.yaml")) or os.path.exists(os.path.join(repo_path, "docker-compose.json"))

    for tool_name, config_files in BUILD_TOOLS.items():
        for config_file in config_files:
            if "*" in config_file:
                import glob
                matches = glob.glob(os.path.join(repo_path, config_file))
                if matches:
                    tools.append(tool_name)
                    break
            elif os.path.exists(os.path.join(repo_path, config_file)):
                tools.append(tool_name)
                break

    return BuildInfo(tools=tools, dockerfile=dockerfile, docker_compose=docker_compose)
