import re
import logging

logger = logging.getLogger(__name__)

# Prompt injection patterns
INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above)\s+(instructions?|prompts?|rules?)",
    r"you\s+are\s+now\s+(a|an|the)",
    r"disregard\s+(previous|all|above)",
    r"forget\s+(everything|all|previous)",
    r"new\s+instructions?:",
    r"system\s*:\s*",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[INST\]",
    r"\[/INST\]",
]

# Secret patterns for redaction
SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "sk-***"),
    (r"sk-ant-[a-zA-Z0-9]{20,}", "sk-ant-***"),
    (r"xai-[a-zA-Z0-9]{20,}", "xai-***"),
    (r"gsk_[a-zA-Z0-9]{20,}", "gsk_***"),
    (r"AIza[a-zA-Z0-9_-]{35}", "AIza***"),
    (r"ghp_[a-zA-Z0-9]{36}", "ghp_***"),
    (r"gho_[a-zA-Z0-9]{36}", "gho_***"),
    (r"(password|secret|token|key)\s*[:=]\s*['\"]?[^\s'\"]{10,}['\"]?", r"\1=***"),
]


def detect_injection(text: str) -> bool:
    """Check if text contains prompt injection patterns."""
    text_lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False


def sanitize_text(text: str) -> str:
    """Redact secrets from text."""
    sanitized = text
    for pattern, replacement in SECRET_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized)
    return sanitized


def sanitize_messages(messages: list) -> list:
    """Sanitize a list of messages, redacting secrets and detecting injection."""
    sanitized = []
    for msg in messages:
        content = msg.get("content", "")
        if content:
            # Redact secrets
            content = sanitize_text(content)
            # Check for injection
            if detect_injection(content):
                logger.warning(f"Prompt injection detected in message")
        sanitized.append({**msg, "content": content})
    return sanitized
