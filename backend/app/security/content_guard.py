"""Content guard for input sanitization and output filtering.

Merges the functionality of prompt_guard.py and sanitizer.py into a single
unified module. Handles both prompt injection detection and secret redaction.
"""

import re
import logging

logger = logging.getLogger(__name__)

# --- Secret Patterns (superset of both original modules) ---
SECRET_PATTERNS = [
    # OpenAI / Anthropic / Groq / xAI keys
    (r"sk-[a-zA-Z0-9]{20,}", "[REDACTED]"),
    (r"sk-ant-[a-zA-Z0-9]{20,}", "[REDACTED]"),
    (r"xai-[a-zA-Z0-9]{20,}", "[REDACTED]"),
    (r"gsk_[a-zA-Z0-9]{20,}", "[REDACTED]"),
    # Google API keys
    (r"AIza[a-zA-Z0-9_-]{35}", "[REDACTED]"),
    # GitHub tokens
    (r"ghp_[a-zA-Z0-9]{36}", "[REDACTED]"),
    (r"gho_[a-zA-Z0-9]{36}", "[REDACTED]"),
    # Slack tokens
    (r"xox[bpsa]-[A-Za-z0-9\-]+", "[REDACTED]"),
    # AWS keys
    (r"(?:AKIA|ASIA)[A-Z0-9]{16}", "[REDACTED]"),
    # Generic password/secret/token/key assignments
    (r"(?:password|secret|token|key|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{10,}['\"]?", "[REDACTED]"),
    # Private keys
    (r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----", "[REDACTED]"),
    # Generic API key assignments
    (r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"]([^'\"]+)['\"]", "[REDACTED]"),
    # Connection strings
    (r"(?:postgres|mysql|mongodb|redis)://[^\s]+", "[REDACTED]"),
]

# --- Prompt Injection Patterns (superset of both original modules) ---
INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?|rules?)",
    r"you\s+are\s+now\s+(?:a|an|the)",
    r"disregard\s+(?:all\s+)?(?:previous|above|prior)",
    r"forget\s+(?:everything|all|previous)",
    r"new\s+instructions?:",
    r"system\s*:\s*",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[INST\]",
    r"\[/INST\]",
    r"<\s*system\s*>",
    r"act\s+as\s+(?:if|though)\s+",
    r"include\s+(?:the\s+)?(?:contents?\s+of|any\s+file)",
    r"when\s+reviewing.*(?:include|output|show|print)",
]


def sanitize_input(content: str) -> str:
    """Redact secrets from content before sending to LLM.

    Args:
        content: Raw content to sanitize.

    Returns:
        Content with secrets redacted.
    """
    sanitized = content
    for pattern, replacement in SECRET_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    return sanitized


def sanitize_output(content: str) -> str:
    """Filter secrets from generated review output before publishing.

    This is the critical output-side defense against prompt injection
    attacks that try to exfiltrate secrets via PR comments.

    Args:
        content: Generated review content to filter.

    Returns:
        Content with any leaked secrets redacted.
    """
    sanitized = content
    for pattern, replacement in SECRET_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    return sanitized


def detect_injection(content: str) -> tuple[bool, list[str]]:
    """Detect prompt injection attempts in content.

    Args:
        content: Content to check for injection patterns.

    Returns:
        Tuple of (is_injection_detected, list_of_matched_patterns).
    """
    matched = []
    content_lower = content.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, content_lower):
            matched.append(pattern)
    return len(matched) > 0, matched


def sanitize_messages(messages: list) -> list:
    """Sanitize a list of messages, redacting secrets and detecting injection.

    Args:
        messages: List of message dicts with 'content' keys.

    Returns:
        Sanitized list of messages.
    """
    sanitized = []
    for msg in messages:
        content = msg.get("content", "")
        if content:
            content = sanitize_input(content)
            is_injection, patterns = detect_injection(content)
            if is_injection:
                logger.warning(f"Prompt injection detected in message: {patterns}")
        sanitized.append({**msg, "content": content})
    return sanitized
