"""Tests for SSRF URL validation."""

import pytest
from unittest.mock import patch, MagicMock
from app.security.url_validator import validate_provider_url, SSRFValidationError


class TestSSRFValidation:
    """Test SSRF protection for provider URLs."""

    def test_rejects_cloud_metadata_ip(self):
        """169.254.169.254 is the AWS/GCP/Azure metadata endpoint."""
        with pytest.raises(SSRFValidationError, match="private/internal network"):
            validate_provider_url("http://169.254.169.254/latest/meta-data/")

    def test_rejects_private_ip_10(self):
        with pytest.raises(SSRFValidationError, match="private/internal network"):
            validate_provider_url("http://10.0.0.1:8080/v1/models")

    def test_rejects_private_ip_192_168(self):
        with pytest.raises(SSRFValidationError, match="private/internal network"):
            validate_provider_url("http://192.168.1.100/api")

    def test_rejects_private_ip_172(self):
        with pytest.raises(SSRFValidationError, match="private/internal network"):
            validate_provider_url("http://172.16.0.1:11434/api")

    def test_rejects_loopback(self):
        with pytest.raises(SSRFValidationError, match="private/internal network"):
            validate_provider_url("http://127.0.0.1:11434/api")

    def test_rejects_http_without_opt_in(self):
        """HTTP to non-localhost should be rejected."""
        with pytest.raises(SSRFValidationError, match="HTTP not allowed"):
            validate_provider_url("http://example.com/api")

    def test_allows_https(self):
        """HTTPS to public endpoints should be allowed."""
        result = validate_provider_url("https://api.openai.com/v1/chat/completions")
        assert result == "https://api.openai.com/v1/chat/completions"

    def test_rejects_ftp_scheme(self):
        with pytest.raises(SSRFValidationError, match="Unsupported URL scheme"):
            validate_provider_url("ftp://example.com/file")

    def test_rejects_javascript_scheme(self):
        with pytest.raises(SSRFValidationError, match="Unsupported URL scheme"):
            validate_provider_url("javascript:alert(1)")

    def test_rejects_empty_hostname(self):
        with pytest.raises(SSRFValidationError, match="no hostname"):
            validate_provider_url("https://")

    def test_allows_empty_url(self):
        """Empty URL should pass through (no validation needed)."""
        result = validate_provider_url("")
        assert result == ""

    @patch("socket.getaddrinfo")
    def test_rejects_dns_rebinding(self, mock_dns):
        """DNS rebinding: resolves to private IP after initial resolution."""
        mock_dns.return_value = [
            (2, 0, 0, "", ("10.0.0.1", 0)),
        ]
        with pytest.raises(SSRFValidationError, match="private/internal network"):
            validate_provider_url("https://evil.example.com/api")

    @patch("socket.getaddrinfo")
    def test_allows_public_ip(self, mock_dns):
        """Public IPs should be allowed."""
        mock_dns.return_value = [
            (2, 0, 0, "", ("104.18.2.100", 443)),
        ]
        result = validate_provider_url("https://api.openai.com/v1")
        assert result == "https://api.openai.com/v1"

    def test_validate_url_safe_returns_bool(self):
        """validate_url_safe should return True/False instead of raising."""
        from app.security.url_validator import validate_url_safe
        assert validate_url_safe("https://api.openai.com/v1") is True
        assert validate_url_safe("http://10.0.0.1/api") is False
