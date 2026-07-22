"""SSRF protection for user-supplied provider URLs.

Validates that user-supplied URLs do not target private/internal networks
after DNS resolution. This prevents Server-Side Request Forgery attacks
via BYOK provider endpoints.
"""

import socket
import ipaddress
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SSRFValidationError(Exception):
    """Raised when a URL fails SSRF validation."""
    pass


# RFC 1918 + link-local + loopback ranges
BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]


def validate_provider_url(
    url: str,
    allow_http_self_hosted: bool = False,
) -> str:
    """Validate a provider URL against SSRF attacks.

    Resolves DNS and checks that the resolved IP is not in a private
    or link-local range. Enforces HTTPS unless self-hosted HTTP is
    explicitly allowed.

    Args:
        url: The URL to validate.
        allow_http_self_hosted: If True, allows http:// for localhost
            (for Ollama). Default False.

    Returns:
        The validated URL (unchanged).

    Raises:
        SSRFValidationError: If the URL fails validation.
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SSRFValidationError(f"Invalid URL format: {e}")

    # Scheme validation
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise SSRFValidationError(f"Unsupported URL scheme: {scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFValidationError("URL has no hostname")

    # Allow Ollama on localhost with explicit opt-in
    is_localhost = hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
    if scheme == "http":
        if is_localhost and allow_http_self_hosted:
            logger.info(f"Allowing HTTP to localhost (self-hosted Ollama): {hostname}")
            return url
        elif not allow_http_self_hosted:
            raise SSRFValidationError(
                f"HTTP not allowed for {hostname}. Use HTTPS, or set "
                f"ALLOW_HTTP_SELF_HOSTED=true for local Ollama."
            )

    # DNS resolution
    try:
        resolved_ips = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise SSRFValidationError(f"DNS resolution failed for {hostname}: {e}")

    # Check each resolved IP against blocked networks
    for family, _, _, _, sockaddr in resolved_ips:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        for network in BLOCKED_NETWORKS:
            if ip in network:
                raise SSRFValidationError(
                    f"URL targets private/internal network: {ip} is in {network}. "
                    f"This could be an SSRF attack."
                )

    return url


def validate_url_safe(url: str, allow_http_self_hosted: bool = False) -> bool:
    """Check if a URL is safe without raising an exception.

    Args:
        url: The URL to check.
        allow_http_self_hosted: If True, allows http:// for localhost.

    Returns:
        True if safe, False if blocked.
    """
    try:
        validate_provider_url(url, allow_http_self_hosted)
        return True
    except SSRFValidationError:
        return False
