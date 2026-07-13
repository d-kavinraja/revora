import os
from typing import List

from app.intelligence.models import SecurityInfo

AUTH_PATTERNS = {
    "jwt": ["jsonwebtoken", "PyJWT", "jwt.encode", "jwt.decode", "Authorization.*Bearer"],
    "session": ["express-session", "cookie-session", "session", "express-session"],
    "oauth": ["passport", "oauth", "OAuth", "github.*oauth", "google.*oauth"],
    "basic_auth": ["basicAuth", "HTTPBasicCredentials"],
    "api_key": ["api_key", "X-API-Key", "apikey"],
    "bearer": ["Bearer", "bearer"],
}


def detect_security(repo_path: str) -> SecurityInfo:
    auth_patterns: list[str] = []
    has_cors = False
    has_rate_limiting = False
    has_https_redirect = False

    files_content = ""
    count = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__"}]
        for f in files:
            if f.endswith((".py", ".js", ".ts", ".tsx", ".jsx")):
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                        files_content += fh.read()[:3000] + "\n"
                except (OSError, IOError):
                    pass
                count += 1
                if count > 100:
                    break
        if count > 100:
            break

    for pattern_name, keywords in AUTH_PATTERNS.items():
        for kw in keywords:
            if kw in files_content:
                auth_patterns.append(pattern_name)
                break

    cors_keywords = ["cors", "CORS", "Access-Control-Allow-Origin"]
    has_cors = any(kw in files_content for kw in cors_keywords)

    rate_limit_keywords = ["rate_limit", "rateLimit", "RateLimit", "throttle", "limiter"]
    has_rate_limiting = any(kw in files_content for kw in rate_limit_keywords)

    https_keywords = ["HTTPSRedirect", "https_redirect", "force_https", "SecureRedirect"]
    has_https_redirect = any(kw in files_content for kw in https_keywords)

    return SecurityInfo(
        auth_patterns=auth_patterns,
        has_cors=has_cors,
        has_rate_limiting=has_rate_limiting,
        has_https_redirect=has_https_redirect,
    )
