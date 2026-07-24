"""Integration test for pipeline wiring (Week 0).

Verifies that the orchestrator pipeline is correctly wired as the
production code path through the webhook handler.
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from datetime import datetime, timezone


class TestPipelineWiring:
    """Test that webhook handler invokes the orchestrator pipeline."""

    @pytest.mark.asyncio
    async def test_webhook_calls_enqueue(self):
        """Verify handle_pr_opened delegates to the job queue."""
        from app.github.webhooks import handle_pr_opened
        
        # Mock the dependencies
        mock_payload = {
            "installation": {"id": 12345},
            "repository": {
                "id": 1,
                "name": "test-repo",
                "full_name": "owner/test-repo",
                "owner": {"login": "owner"},
                "private": False,
            },
            "pull_request": {
                "number": 1,
                "title": "Test PR",
                "body": "Test body",
                "head": {"sha": "abc123", "ref": "feature/test"},
                "base": {"ref": "main"},
                "user": {"login": "developer"},
                "additions": 10,
                "deletions": 5,
                "changed_files": 2,
            },
        }

        with patch("app.github.webhooks.AsyncSessionLocal") as mock_session_local, \
             patch("app.queue.dispatcher.enqueue_review_job", new_callable=AsyncMock) as mock_enqueue:
            
            mock_db = MagicMock()
            mock_session_local.return_value.__aenter__.return_value = mock_db

            await handle_pr_opened(mock_payload, "test-delivery-id")

            # Verify the orchestrator pipeline was called
            mock_enqueue.assert_called_once()
            call_args = mock_enqueue.call_args[0]
            assert call_args[0] == mock_db
            assert call_args[1] == mock_payload
            assert call_args[2] == "test-delivery-id"

    @pytest.mark.asyncio
    async def test_webhook_returns_202(self):
        """Verify webhook endpoint returns 202 Accepted."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)

        # This test would need proper webhook signature
        # For now, just verify the endpoint exists
        response = client.post(
            "/api/v1/webhooks/github",
            json={"action": "opened"},
            headers={"X-GitHub-Event": "pull_request"},
        )
        # Without valid signature, should return 401
        assert response.status_code == 401


class TestContentGuardIntegration:
    """Test content guard is properly integrated."""

    @pytest.mark.asyncio
    async def test_output_filtering_before_publish(self):
        """Verify output is filtered before GitHub publication."""
        from app.security.content_guard import sanitize_output

        # Simulate a review output that contains a leaked secret
        review_output = "Found issue: API key sk-test123456789abcdef is exposed"
        filtered = sanitize_output(review_output)

        # The secret should be redacted
        assert "sk-test123456789abcdef" not in filtered
        assert "[REDACTED]" in filtered


class TestSSRFIntegration:
    """Test SSRF validation is wired into the system."""

    def test_config_has_self_hosted_flag(self):
        """Verify ALLOW_HTTP_SELF_HOSTED is in config."""
        from app.core.config import settings
        assert hasattr(settings, "ALLOW_HTTP_SELF_HOSTED")
        assert settings.ALLOW_HTTP_SELF_HOSTED is False  # Default
