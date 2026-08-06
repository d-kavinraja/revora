"""Security pattern detection engine.

Detects authentication patterns, CORS, rate limiting, and HTTPS configuration.
Uses the shared RepoWalker for efficient filesystem access.
"""


from app.core.constants import MAX_FILES_PER_DETECTOR
from app.intelligence._async_util import run_async
from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.intelligence.models import SecurityInfo

AUTH_PATTERNS = [
    "Authorization",
    "Bearer",
    "JWT",
    "token",
    "authenticate",
    "login",
    "passport",
    "oauth",
    "session",
    "cookie",
]

CORS_PATTERNS = ["CORS", "cors", "Access-Control-Allow-Origin"]
RATE_LIMIT_PATTERNS = ["rate_limit", "rateLimit", "RateLimit", "throttle", "limiter"]
HTTPS_PATTERNS = ["HTTPS", "https_redirect", "ssl", "tls"]


class SecurityDetector(BaseDetector):
    """Detects security patterns in the repository."""

    @property
    def name(self) -> str:
        return "security_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect security patterns using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with security info.
        """
        auth_patterns: list[str] = []
        has_cors = False
        has_rate_limiting = False
        has_https_redirect = False

        # Check config files for security patterns
        config_files = [
            fp for fp in walker.file_paths
            if any(fp.endswith(ext) for ext in [
                ".py", ".js", ".ts", ".tsx", ".jsx",
                ".go", ".java", ".rb", ".php",
                ".yaml", ".yml", ".json", ".toml",
                ".env", ".cfg", ".ini",
            ])
        ]

        files_checked = 0
        for fp in config_files:
            if files_checked >= MAX_FILES_PER_DETECTOR:
                break

            content = await walker.get_content(fp, max_chars=3000)
            if not content:
                continue

            files_checked += 1

            # Check auth patterns
            for pattern in AUTH_PATTERNS:
                if pattern in content and pattern not in auth_patterns:
                    auth_patterns.append(pattern)

            # Check CORS
            if not has_cors:
                has_cors = any(p in content for p in CORS_PATTERNS)

            # Check rate limiting
            if not has_rate_limiting:
                has_rate_limiting = any(p in content for p in RATE_LIMIT_PATTERNS)

            # Check HTTPS
            if not has_https_redirect:
                has_https_redirect = any(p in content for p in HTTPS_PATTERNS)

        return DetectorResult(
            success=True,
            data={
                "auth_patterns": auth_patterns,
                "has_cors": has_cors,
                "has_rate_limiting": has_rate_limiting,
                "has_https_redirect": has_https_redirect,
            },
            confidence=0.7 if auth_patterns else 0.3,
        )


# Legacy function interface for backward compatibility
def detect_security(repo_path: str) -> SecurityInfo:
    """Detect security patterns in a repository (legacy interface)."""
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = SecurityDetector()
        result = await detector.detect(walker)
        data = result.data
        return SecurityInfo(
            auth_patterns=data.get("auth_patterns", []),
            has_cors=data.get("has_cors", False),
            has_rate_limiting=data.get("has_rate_limiting", False),
            has_https_redirect=data.get("has_https_redirect", False),
        )

    return run_async(_detect())
