from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LanguageInfo:
    name: str
    file_count: int
    percentage: float


@dataclass
class FrameworkInfo:
    name: str
    version: Optional[str] = None
    config_file: Optional[str] = None


@dataclass
class ArchitectureInfo:
    pattern: str  # layered, ddd, clean, hexagonal, mvc, microservices, monorepo
    confidence: float
    indicators: list[str] = field(default_factory=list)


@dataclass
class DatabaseInfo:
    type: Optional[str] = None  # postgresql, mysql, sqlite, mongodb, redis
    orm: Optional[str] = None  # sqlalchemy, prisma, typeorm, drizzle, mongoose
    indicators: list[str] = field(default_factory=list)


@dataclass
class PackageManagerInfo:
    name: Optional[str] = None  # npm, yarn, pnpm, pip, poetry, cargo, go mod
    lock_file: Optional[str] = None
    config_file: Optional[str] = None


@dataclass
class CIInfo:
    provider: Optional[str] = None  # github_actions, gitlab_ci, circleci, jenkins
    config_file: Optional[str] = None
    workflows: list[str] = field(default_factory=list)


@dataclass
class BuildInfo:
    tools: list[str] = field(default_factory=list)  # webpack, vite, esbuild, gradle, maven
    dockerfile: bool = False
    docker_compose: bool = False


@dataclass
class SecurityInfo:
    auth_patterns: list[str] = field(default_factory=list)  # jwt, session, oauth, basic
    has_cors: bool = False
    has_rate_limiting: bool = False
    has_https_redirect: bool = False


@dataclass
class TestingInfo:
    framework: Optional[str] = None  # jest, pytest, go test, vitest, mocha
    has_tests: bool = False
    test_count: int = 0
    test_directories: list[str] = field(default_factory=list)


@dataclass
class IntelligenceResult:
    languages: list[LanguageInfo] = field(default_factory=list)
    frameworks: list[FrameworkInfo] = field(default_factory=list)
    architecture: Optional[ArchitectureInfo] = None
    database: Optional[DatabaseInfo] = None
    package_manager: Optional[PackageManagerInfo] = None
    testing: Optional[TestingInfo] = None
    build: Optional[BuildInfo] = None
    ci: Optional[CIInfo] = None
    security: Optional[SecurityInfo] = None
    repo_type: str = "standard"  # monorepo, microservices, standard
    cloud_provider: Optional[str] = None  # aws, gcp, azure, vercel, netlify
    caching: Optional[str] = None  # redis, memcached, none
    queues: Optional[str] = None  # rabbitmq, sqs, celery, bull
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "languages": [{"name": l.name, "file_count": l.file_count, "percentage": l.percentage} for l in self.languages],
            "frameworks": [{"name": f.name, "version": f.version, "config_file": f.config_file} for f in self.frameworks],
            "architecture": {"pattern": self.architecture.pattern, "confidence": self.architecture.confidence, "indicators": self.architecture.indicators} if self.architecture else None,
            "database": {"type": self.database.type, "orm": self.database.orm, "indicators": self.database.indicators} if self.database else None,
            "package_manager": {"name": self.package_manager.name, "lock_file": self.package_manager.lock_file} if self.package_manager else None,
            "testing": {"framework": self.testing.framework, "has_tests": self.testing.has_tests, "test_count": self.testing.test_count} if self.testing else None,
            "build": {"tools": self.build.tools, "dockerfile": self.build.dockerfile, "docker_compose": self.build.docker_compose} if self.build else None,
            "ci": {"provider": self.ci.provider, "config_file": self.ci.config_file} if self.ci else None,
            "security": {"auth_patterns": self.security.auth_patterns, "has_cors": self.security.has_cors} if self.security else None,
            "repo_type": self.repo_type,
            "cloud_provider": self.cloud_provider,
            "caching": self.caching,
            "queues": self.queues,
            "confidence": self.confidence,
        }
