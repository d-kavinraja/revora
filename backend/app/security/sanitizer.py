import re
import logging

logger = logging.getLogger(__name__)

SECRET_PATTERNS = [
    (r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"]([^'\"]+)['\"]", "API_KEY"),
    (r"(?:secret|SECRET)\s*[:=]\s*['\"]([^'\"]+)['\"]", "SECRET"),
    (r"(?:password|passwd|pwd)\s*[:=]\s*['\"]([^'\"]+)['\"]", "PASSWORD"),
    (r"(?:token|TOKEN)\s*[:=]\s*['\"]([^'\"]+)['\"]", "TOKEN"),
    (r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----", "PRIVATE_KEY"),
    (r"ghp_[A-Za-z0-9]{36}", "GITHUB_TOKEN"),
    (r"sk-[A-Za-z0-9]{32,}", "OPENAI_KEY"),
    (r"AIza[0-9A-Za-z\-_]{35}", "GOOGLE_KEY"),
    (r"xox[bpsa]-[A-Za-z0-9\-]+", "SLACK_TOKEN"),
]

INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?)",
    r"you\s+are\s+now\s+(?:a|an)\s+",
    r"disregard\s+(?:all\s+)?(?:previous|above|prior)",
    r"system\s*:\s*you\s+are",
    r"<\s*system\s*>",
    r"act\s+as\s+(?:if|though)\s+",
]


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern, label in SECRET_PATTERNS:
        redacted = re.sub(pattern, f"[REDACTED_{label}]", redacted, flags=re.IGNORECASE)
    return redacted


def detect_prompt_injection(text: str) -> bool:
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def sanitize_content(text: str) -> str:
    text = redact_secrets(text)
    if detect_prompt_injection(text):
        logger.warning("Prompt injection detected in content — flagging")
    return text


def sanitize_file_content(content: str, file_path: str) -> str:
    if file_path.endswith((".md", ".txt", ".rst")):
        if detect_prompt_injection(content):
            logger.warning(f"Prompt injection detected in {file_path} — sanitizing")
            return "[Content flagged for potential prompt injection — redacted]"
    return redact_secrets(content)
