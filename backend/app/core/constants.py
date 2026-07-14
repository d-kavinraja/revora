"""Centralized constants for the Revora codebase.

All shared constants (skip directories, file patterns, limits) are defined here
to avoid duplication across modules.
"""

from typing import FrozenSet

# Directories to skip during filesystem traversal
SKIP_DIRS: FrozenSet[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".next",
    ".nuxt",
    "venv",
    ".venv",
    "env",
    ".env",
    "build",
    "dist",
    "target",
    "vendor",
    ".idea",
    ".vscode",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".eggs",
    "*.egg-info",
    "eggs",
    "parts",
    "develop-eggs",
    "downloads",
    "sdist",
    "wheels",
    ".sass-cache",
    ".cache",
    ".parcel-cache",
    ".turbo",
    "tmp",
    "temp",
})

# File extensions to skip (binary, compiled, etc.)
SKIP_EXTENSIONS: FrozenSet[str] = frozenset({
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".dat",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".webp",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".lock",
    ".min.js",
    ".min.css",
    ".map",
})

# Maximum file size to read (in characters)
MAX_FILE_READ_CHARS: int = 10000

# Maximum number of files to scan per detector
MAX_FILES_PER_DETECTOR: int = 200

# Token estimation: characters per token (rough approximation)
CHARS_PER_TOKEN: int = 4

# Default token budget for context retrieval
DEFAULT_TOKEN_BUDGET: int = 10000

# Maximum review limit for API queries
MAX_REVIEW_LIMIT: int = 100

# SSE stream maximum connection lifetime (in seconds)
SSE_MAX_CONNECTION_LIFETIME: int = 300

# SSE heartbeat interval (in seconds)
SSE_HEARTBEAT_INTERVAL: int = 30

# LLM call timeout (in seconds)
LLM_DEFAULT_TIMEOUT: int = 60

# GitHub API timeout (in seconds)
GITHUB_API_TIMEOUT: int = 30

# Database connection pool settings
DB_POOL_SIZE: int = 20
DB_MAX_OVERFLOW: int = 10
DB_POOL_TIMEOUT: int = 30
DB_POOL_RECYCLE: int = 3600

# Rate limiting defaults
RATE_LIMIT_LOGIN: int = 5  # per minute per IP
RATE_LIMIT_REGISTER: int = 3  # per minute per IP
RATE_LIMIT_GITHUB_AUTH: int = 10  # per minute per IP

# JWT token expiry (in minutes)
JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day

# Provider fallback configuration
PROVIDER_MAX_RETRIES: int = 3
PROVIDER_BACKOFF_MAX_SECONDS: int = 8

# Usage history maximum size
USAGE_HISTORY_MAX_SIZE: int = 1000

# Repository health score weights
HEALTH_WEIGHT_LANGUAGE: float = 0.15
HEALTH_WEIGHT_FRAMEWORK: float = 0.15
HEALTH_WEIGHT_ARCHITECTURE: float = 0.15
HEALTH_WEIGHT_TESTING: float = 0.20
HEALTH_WEIGHT_SECURITY: float = 0.20
HEALTH_WEIGHT_DOCUMENTATION: float = 0.15
