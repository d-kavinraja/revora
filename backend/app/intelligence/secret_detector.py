"""Secret detection engine.

Detects hardcoded credentials, API keys, and secrets in source code.
Uses deterministic pattern matching without LLM calls.
"""

import re
from typing import List, Dict

from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.core.constants import MAX_FILES_PER_DETECTOR


# Secret patterns: (name, regex pattern, severity)
SECRET_PATTERNS = [
    ("AWS Access Key", r"AKIA[0-9A-Z]{16}", "critical"),
    ("AWS Secret Key", r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}", "critical"),
    ("GitHub Token", r"ghp_[A-Za-z0-9]{36}", "critical"),
    ("GitHub OAuth", r"gho_[A-Za-z0-9]{36}", "critical"),
    ("GitHub App Token", r"(?:ghu|ghs)_[A-Za-z0-9]{36}", "critical"),
    ("GitLab Token", r"glpat-[A-Za-z0-9\-_]{20,}", "critical"),
    ("Slack Token", r"xox[baprs]-[0-9a-zA-Z\-]{10,}", "critical"),
    ("Slack Webhook", r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+", "high"),
    ("Google API Key", r"AIza[0-9A-Za-z\-_]{35}", "critical"),
    ("Heroku API Key", r"(?i)heroku.*key\s*[:=]\s*['\"]?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "critical"),
    ("Stripe Key", r"sk_live_[0-9a-zA-Z]{24,}", "critical"),
    ("Stripe Publishable", r"pk_live_[0-9a-zA-Z]{24,}", "high"),
    ("Twilio API Key", r"SK[0-9a-fA-F]{32}", "critical"),
    ("SendGrid Key", r"SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}", "critical"),
    ("Mailgun Key", r"key-[0-9a-zA-Z]{32}", "critical"),
    ("Private Key Block", r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----", "critical"),
    ("Password in Code", r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"](?![\s'\"])[^'\"]{8,}", "high"),
    ("API Key Assignment", r"(?i)(?:api_key|apikey|api_secret)\s*[:=]\s*['\"](?![\s'\"])[A-Za-z0-9\-_]{16,}", "high"),
    ("Secret Assignment", r"(?i)(?:client_secret|secret_key)\s*[:=]\s*['\"](?![\s'\"])[A-Za-z0-9\-_]{16,}", "high"),
    ("Token Assignment", r"(?i)(?:access_token|auth_token)\s*[:=]\s*['\"](?![\s'\"])[A-Za-z0-9\-_]{16,}", "high"),
    ("Connection String", r"(?i)(?:mysql|postgres|postgresql|mongodb|redis)://[^\s'\"]{20,}", "critical"),
    ("JWT Token", r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_.+/=]+", "high"),
]

# File extensions to scan
SCAN_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java",
    ".rb", ".php", ".cs", ".swift", ".kt", ".scala",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
    ".env", ".sh", ".bash", ".zsh", ".dockerfile",
    ".tf", ".hcl", ".proto",
}

# Files to skip
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "Cargo.lock",
    "go.sum", "composer.lock", "mix.lock",
}


class SecretDetector(BaseDetector):
    """Detects hardcoded credentials and secrets in source code."""

    @property
    def name(self) -> str:
        return "secret_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect secrets using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with detected secrets.
        """
        findings: List[Dict] = []
        files_scanned = 0

        # Collect files to scan
        scan_files = [
            fp for fp in walker.file_paths
            if any(fp.endswith(ext) for ext in SCAN_EXTENSIONS)
            and fp.split("/")[-1] not in SKIP_FILES
        ]

        for fp in scan_files:
            if files_scanned >= MAX_FILES_PER_DETECTOR:
                break

            content = await walker.get_content(fp, max_chars=5000)
            if not content:
                continue

            files_scanned += 1

            # Check each pattern
            for pattern_name, regex, severity in SECRET_PATTERNS:
                matches = re.finditer(regex, content)
                for match in matches:
                    # Get line number
                    line_num = content[:match.start()].count("\n") + 1

                    # Get the matched text (redacted)
                    matched_text = match.group()
                    redacted = matched_text[:4] + "*" * (len(matched_text) - 4)

                    findings.append({
                        "file": fp,
                        "line": line_num,
                        "type": pattern_name,
                        "severity": severity,
                        "redacted": redacted,
                    })

        return DetectorResult(
            success=True,
            data={
                "findings": findings,
                "findings_count": len(findings),
                "files_scanned": files_scanned,
                "critical_count": len([f for f in findings if f["severity"] == "critical"]),
                "high_count": len([f for f in findings if f["severity"] == "high"]),
            },
            confidence=0.9 if findings else 0.0,
        )
