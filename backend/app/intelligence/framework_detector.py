import os
from pathlib import Path
from typing import List, Optional, Tuple

from app.intelligence.models import FrameworkInfo

FRAMEWORK_SIGNATURES: list[Tuple[str, list[str], Optional[str]]] = [
    # JavaScript / TypeScript
    ("Next.js", ["next.config.js", "next.config.ts", "next.config.mjs"], None),
    ("React", ["react", "react-dom"], "package.json"),
    ("Vue.js", ["vue", "nuxt"], "package.json"),
    ("Nuxt", ["nuxt.config.js", "nuxt.config.ts"], None),
    ("Svelte", ["svelte", "@sveltejs/kit"], "package.json"),
    ("Angular", ["@angular/core"], "package.json"),
    ("Express.js", ["express"], "package.json"),
    ("Fastify", ["fastify"], "package.json"),
    ("NestJS", ["@nestjs/core"], "package.json"),
    ("Remix", ["@remix-run/react"], "package.json"),
    ("Vite", ["vite"], "package.json"),
    ("Webpack", ["webpack"], "package.json"),

    # Python
    ("FastAPI", ["fastapi"], "requirements.txt"),
    ("FastAPI", ["fastapi"], "pyproject.toml"),
    ("Django", ["django"], "requirements.txt"),
    ("Django", ["django"], "pyproject.toml"),
    ("Flask", ["flask"], "requirements.txt"),
    ("Flask", ["flask"], "pyproject.toml"),
    ("Starlette", ["starlette"], "requirements.txt"),
    ("Celery", ["celery"], "requirements.txt"),
    ("Celery", ["celery"], "pyproject.toml"),

    # Go
    ("Gin", ["github.com/gin-gonic/gin"], "go.mod"),
    ("Echo", ["github.com/labstack/echo"], "go.mod"),
    ("Fiber", ["github.com/gofiber/fiber"], "go.mod"),
    ("Chi", ["github.com/go-chi/chi"], "go.mod"),

    # Java / Kotlin
    ("Spring Boot", ["org.springframework.boot"], "pom.xml"),
    ("Spring Boot", ["org.springframework.boot"], "build.gradle"),
    ("Micronaut", ["io.micronaut"], "build.gradle"),

    # Rust
    ("Actix Web", ["actix-web"], "Cargo.toml"),
    ("Axum", ["axum"], "Cargo.toml"),
    ("Rocket", ["rocket"], "Cargo.toml"),

    # Ruby
    ("Rails", ["rails"], "Gemfile"),
    ("Sinatra", ["sinatra"], "Gemfile"),
]


def detect_frameworks(repo_path: str) -> List[FrameworkInfo]:
    frameworks: list[FrameworkInfo] = []
    seen = set()

    for name, signatures, config_file in FRAMEWORK_SIGNATURES:
        if name in seen:
            continue

        if config_file:
            config_path = os.path.join(repo_path, config_file)
            if not os.path.exists(config_path):
                continue

            try:
                with open(config_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if any(sig in content for sig in signatures):
                    frameworks.append(FrameworkInfo(name=name, config_file=config_file))
                    seen.add(name)
            except (OSError, IOError):
                continue
        else:
            for sig in signatures:
                if os.path.exists(os.path.join(repo_path, sig)):
                    frameworks.append(FrameworkInfo(name=name, config_file=sig))
                    seen.add(name)
                    break

    return frameworks
