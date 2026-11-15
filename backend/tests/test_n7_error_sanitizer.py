"""N7 — provider/tooling error detail cannot reach API responses or stored rows."""
import uuid
from datetime import UTC, datetime

from app.models.github import Installation, PullRequest, Repository
from app.models.review import Review
from app.models.execution import ReviewExecution
from app.security.error_sanitizer import (
    MAX_ERROR_MESSAGE_LENGTH,
    sanitize_error_message,
)


def test_sanitize_error_message_strips_urls_and_keys():
    raw = (
        "POST https://api.openai.com/v1/chat/completions failed "
        "with Bearer sk-livekey1234567890 and gsk_abc123def456\n"
        "token: super-secret-value"
    )
    cleaned = sanitize_error_message(raw)

    assert "https://api.openai.com" not in cleaned
    assert "sk-livekey1234567890" not in cleaned
    assert "gsk_abc123def456" not in cleaned
    assert "super-secret-value" not in cleaned
    assert "[redacted]" in cleaned


def test_sanitize_error_message_truncates_long_messages():
    cleaned = sanitize_error_message("x" * (MAX_ERROR_MESSAGE_LENGTH + 500))
    assert len(cleaned) == MAX_ERROR_MESSAGE_LENGTH


def test_sanitize_error_message_handles_non_string_input():
    assert "boom" in sanitize_error_message(RuntimeError("boom"))
    assert sanitize_error_message(None) == ""


async def test_reviews_api_redacts_persisted_error_message(
    test_db, client, mock_user
):
    raw_error = "git clone https://github.com/private/secret-repo failed: x"

    installation = Installation(
        id=uuid.uuid4(),
        installation_id=808080,
        account_id=8080,
        account_login="n7-owner",
        account_type="User",
        user_id=mock_user.id,
        repository_selection="all",
        permissions={},
        events={},
        permissions_ok=True,
        app_id=12345,
    )
    test_db.add(installation)
    await test_db.flush()

    repo = Repository(
        id=uuid.uuid4(),
        github_id=808080,
        name="n7-repo",
        full_name="n7-owner/n7-repo",
        installation_id=installation.id,
        reviews_enabled=True,
    )
    test_db.add(repo)
    await test_db.flush()

    pr = PullRequest(
        id=uuid.uuid4(),
        repo_id=repo.id,
        pr_number=9,
        title="N7 review",
        author="author",
        head_sha="d" * 40,
        base_branch="main",
        head_branch="feat",
        status="open",
    )
    test_db.add(pr)
    await test_db.flush()

    review = Review(id=uuid.uuid4(), pr_id=pr.id, status="failed")
    test_db.add(review)
    await test_db.flush()

    execution = ReviewExecution(
        id=uuid.uuid4(),
        review_id=review.id,
        execution_number=1,
        trigger="opened",
        status="failed",
        commit_sha="d" * 40,
        error_message=raw_error,
        completed_at=datetime.now(UTC),
    )
    test_db.add(execution)
    await test_db.commit()

    response = client.get("/api/v1/reviews")
    assert response.status_code == 200
    body = response.text
    assert "https://github.com/private/secret-repo" not in body
    assert "[redacted]" in body
