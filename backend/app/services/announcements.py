"""Announcement validation and public-active query (phase 7, §13).

Admin-managed announcements are informational only: they never change
access controls, feature flags or the maintenance state (§12.5
separation). Stored copy is always plain text — the sanitizer rejects
control characters and markup instead of escaping it, so anything that
reaches the public API is display-safe.
"""

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import Announcement

MAX_TITLE_LEN = 200
MAX_MESSAGE_LEN = 2000
MAX_LINK_URL_LEN = 500
MAX_LINK_LABEL_LEN = 100


class AnnouncementValidationError(ValueError):
    """Invalid announcement payload -> HTTP 400 at the endpoint boundary."""


def _as_utc(value: datetime | None) -> datetime | None:
    """Reinterpret naive datetimes as UTC (SQLite round-trip parity)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def sanitize_text(value: str, *, field: str, max_length: int) -> str:
    """Trim, length-cap and reject control characters / HTML markup."""
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise AnnouncementValidationError(f"{field} must not be empty")
    if len(text) > max_length:
        raise AnnouncementValidationError(
            f"{field} must be at most {max_length} characters"
        )
    for char in text:
        if ord(char) < 32 and char not in ("\n", "\t"):
            raise AnnouncementValidationError(
                f"{field} must not contain control characters"
            )
    if "<" in text or ">" in text:
        raise AnnouncementValidationError(f"{field} must not contain HTML markup")
    return text


def validate_schedule(
    starts_at: datetime | None, ends_at: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """Reject an inverted window; equal bounds mean "starts and ends now"."""
    normalized_start = _as_utc(starts_at)
    normalized_end = _as_utc(ends_at)
    if (
        normalized_start is not None
        and normalized_end is not None
        and normalized_start > normalized_end
    ):
        raise AnnouncementValidationError("starts_at must not be after ends_at")
    return normalized_start, normalized_end


def validate_link(
    link_url: str | None, link_label: str | None
) -> tuple[str | None, str | None]:
    """Validate the optional call-to-action link (http/https only)."""
    url = link_url.strip() if link_url else None
    label = link_label.strip() if link_label else None
    if url:
        if len(url) > MAX_LINK_URL_LEN:
            raise AnnouncementValidationError(
                f"link_url must be at most {MAX_LINK_URL_LEN} characters"
            )
        if not url.startswith(("http://", "https://")):
            raise AnnouncementValidationError(
                "link_url must start with http:// or https://"
            )
    if label:
        if not url:
            raise AnnouncementValidationError("link_label requires link_url")
        if len(label) > MAX_LINK_LABEL_LEN:
            raise AnnouncementValidationError(
                f"link_label must be at most {MAX_LINK_LABEL_LEN} characters"
            )
    return url, label


async def public_announcements(
    db: AsyncSession, *, now: datetime | None = None
) -> list[Announcement]:
    """Published, enabled, currently-active announcements only (B28).

    The window is half-open ``[starts_at, ends_at)``: a missing bound means
    "no restriction on that side" and an announcement whose `ends_at` has
    passed is expired and never returned.
    """
    now = _as_utc(now) or datetime.now(UTC)
    rows = (
        await db.execute(
            select(Announcement)
            .where(
                Announcement.state == "published",
                Announcement.is_enabled.is_(True),
                or_(
                    Announcement.starts_at.is_(None),
                    Announcement.starts_at <= now,
                ),
                or_(
                    Announcement.ends_at.is_(None),
                    Announcement.ends_at > now,
                ),
            )
            .order_by(Announcement.created_at.desc())
        )
    ).scalars().all()
    return list(rows)
