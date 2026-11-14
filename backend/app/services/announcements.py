"""Announcement validation, public-active query and display policies.

Admin-managed announcements are informational only: they never change
access controls, feature flags or the maintenance state (§12.5
separation). Stored copy is always plain text — the sanitizer rejects
control characters and markup instead of escaping it, so anything that
reaches the public API is display-safe.

Display policies (§13) live here as the single source of truth: the
frontend never re-implements them. Visibility is computed per *subject*:

* a signed-in user (``subject_type='user'``), or
* an anonymous browser device (``subject_type='device'``).

One subject's dismissal never affects another subject — not another user,
and not a different browser.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import (
    ANNOUNCEMENT_AUDIENCES,
    ANNOUNCEMENT_DISPLAY_POLICIES,
    Announcement,
    AnnouncementState,
)

MAX_TITLE_LEN = 200
MAX_MESSAGE_LEN = 2000
MAX_LINK_URL_LEN = 500
MAX_LINK_LABEL_LEN = 100

#: Fields whose change bumps ``Announcement.version`` (published content).
VERSION_BUMP_FIELDS = frozenset(
    {
        "title",
        "message",
        "kind",
        "link_url",
        "link_label",
        "starts_at",
        "ends_at",
        "display_policy",
        "recur_interval_minutes",
        "audience",
    }
)

#: Cookie carrying the anonymous device id. Not a credential: it only
#: scopes anonymous dismissals to one browser.
DEVICE_COOKIE_NAME = "revora_device_id"

#: Cookie carrying the anonymous device creation time, used as the
#: "session start" for the ``every_login`` policy when nobody is signed in.
DEVICE_SINCE_COOKIE_NAME = "revora_device_since"


class AnnouncementValidationError(ValueError):
    """Invalid announcement payload -> HTTP 400 at the endpoint boundary."""


def as_utc(value: datetime | None) -> datetime | None:
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
    normalized_start = as_utc(starts_at)
    normalized_end = as_utc(ends_at)
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


def validate_display_policy(
    display_policy: str | None,
    recur_interval_minutes: int | None,
    *,
    previous_policy: str | None = None,
    previous_interval: int | None = None,
    interval_provided: bool = False,
) -> tuple[str, int | None]:
    """Validate the display policy + recurrence interval pair.

    The recurrence interval is required (and must be positive) for the
    ``recurring`` policy and is cleared for every other policy.

    ``display_policy``/``recur_interval_minutes`` are the *incoming* values
    (``None`` = not supplied unless ``interval_provided`` is set);
    ``previous_policy``/``previous_interval`` carry the stored values.
    """
    policy = (display_policy or previous_policy or "every_login").strip()
    if policy not in ANNOUNCEMENT_DISPLAY_POLICIES:
        raise AnnouncementValidationError(
            "display_policy must be one of: "
            + ", ".join(ANNOUNCEMENT_DISPLAY_POLICIES)
        )

    provided = interval_provided or recur_interval_minutes is not None

    if policy == "recurring":
        if provided:
            interval = recur_interval_minutes
        elif previous_policy == "recurring":
            interval = previous_interval
        else:
            interval = None
        if interval is None:
            raise AnnouncementValidationError(
                "recur_interval_minutes is required for the recurring display policy"
            )
        if interval < 1:
            raise AnnouncementValidationError(
                "recur_interval_minutes must be at least 1 minute"
            )
        return policy, interval

    if provided and recur_interval_minutes is not None:
        raise AnnouncementValidationError(
            "recur_interval_minutes is only allowed with the recurring display policy"
        )
    # A non-recurring policy never carries an interval — clear it.
    return policy, None


def validate_audience(audience: str | None) -> str:
    """Validate the reserved audience vocabulary."""
    value = (audience or "all").strip()
    if value not in ANNOUNCEMENT_AUDIENCES:
        raise AnnouncementValidationError(
            "audience must be one of: " + ", ".join(ANNOUNCEMENT_AUDIENCES)
        )
    return value


@dataclass(frozen=True)
class Subject:
    """Who a dismissal belongs to.

    ``user`` subjects are signed-in accounts; ``device`` subjects are
    anonymous browsers identified by a random, non-credential id.
    """

    subject_type: str
    subject_id: str
    #: Session start used by the ``every_login`` policy.
    session_start: datetime

    @property
    def key(self) -> tuple[str, str]:
        return (self.subject_type, self.subject_id)


def user_subject(user_id: uuid.UUID, last_login_at: datetime | None) -> Subject:
    """Subject for a signed-in user.

    The session start is the user's last login: a new login advances it, so
    ``every_login`` announcements become eligible again exactly once per
    login session.
    """
    start = as_utc(last_login_at) or datetime.now(UTC)
    return Subject(subject_type="user", subject_id=str(user_id), session_start=start)


def device_subject(device_id: str, device_since: datetime | None) -> Subject:
    """Subject for an anonymous browser.

    The session start is the device creation time, which approximates a
    browser session for the ``every_login`` policy.
    """
    start = as_utc(device_since) or datetime.now(UTC)
    return Subject(subject_type="device", subject_id=device_id, session_start=start)


def normalize_device_id(raw: str | None) -> str | None:
    """Accept a device id only when it looks like a UUID."""
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw.strip()))
    except (ValueError, AttributeError):
        return None


def _state_dismissed(state: AnnouncementState | None) -> datetime | None:
    if state is None:
        return None
    return as_utc(state.dismissed_at)


def _state_seen(state: AnnouncementState | None) -> datetime | None:
    if state is None:
        return None
    return as_utc(state.last_seen_at)


def is_visible(
    *,
    display_policy: str,
    recur_interval_minutes: int | None,
    state: AnnouncementState | None,
    session_start: datetime,
    now: datetime,
    is_dismissible: bool = True,
) -> bool:
    """Whether an announcement is visible to one subject right now.

    Non-dismissible announcements are never hidden by a subject's dismissal
    or seen marker: they stay visible until the admin disables, unpublishes
    or updates them.

    * ``once_until_dismissed`` — visible until the subject dismisses it.
      A version bump invalidates the dismissal, so updated content shows
      again.
    * ``every_login`` — shown once per login session. It stays hidden for
      the rest of the session once it has been dismissed *or* seen.
    * ``recurring`` — after dismissal it reappears once the configured
      interval has elapsed.
    """
    if not is_dismissible:
        return True

    dismissed_at = _state_dismissed(state)
    last_seen_at = _state_seen(state)

    if display_policy == "once_until_dismissed":
        return dismissed_at is None

    if display_policy == "every_login":
        if dismissed_at is not None and dismissed_at >= session_start:
            return False
        return not (
            last_seen_at is not None and last_seen_at >= session_start
        )

    if display_policy == "recurring":
        if dismissed_at is None:
            return True
        interval = recur_interval_minutes or 0
        return now >= dismissed_at + timedelta(minutes=interval)

    # Unknown policy: never silently hide content — show it.
    return True


def next_visible_at(
    *,
    display_policy: str,
    recur_interval_minutes: int | None,
    state: AnnouncementState | None,
    session_start: datetime,
) -> datetime | None:
    """When a hidden announcement becomes visible again (None = never)."""
    dismissed_at = _state_dismissed(state)
    last_seen_at = _state_seen(state)

    if display_policy == "once_until_dismissed":
        # Only a published-content update (version bump) makes it eligible.
        return None

    if display_policy == "every_login":
        if dismissed_at is not None and dismissed_at >= session_start:
            return None
        if last_seen_at is not None and last_seen_at >= session_start:
            return None
        return None

    if display_policy == "recurring" and dismissed_at is not None:
        interval = recur_interval_minutes or 0
        return dismissed_at + timedelta(minutes=interval)

    return None


async def _states_for(
    db: AsyncSession, subject: Subject, announcements: list[Announcement]
) -> dict[tuple[uuid.UUID, int], AnnouncementState]:
    """Load the subject's state rows for the given announcements."""
    if not announcements:
        return {}
    rows = (
        await db.execute(
            select(AnnouncementState).where(
                and_(
                    AnnouncementState.subject_type == subject.subject_type,
                    AnnouncementState.subject_id == subject.subject_id,
                    AnnouncementState.announcement_id.in_(
                        [row.id for row in announcements]
                    ),
                )
            )
        )
    ).scalars().all()
    return {(row.announcement_id, row.announcement_version): row for row in rows}


async def public_announcements(
    db: AsyncSession, *, now: datetime | None = None
) -> list[Announcement]:
    """Published, enabled, currently-active announcements only (B28).

    The window is half-open ``[starts_at, ends_at)``: a missing bound means
    "no restriction on that side" and an announcement whose `ends_at` has
    passed is expired and never returned.
    """
    now = as_utc(now) or datetime.now(UTC)
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


async def visible_announcements(
    db: AsyncSession,
    subject: Subject,
    *,
    now: datetime | None = None,
) -> list[tuple[Announcement, AnnouncementState | None]]:
    """Published announcements this subject should see right now.

    Returns ``(announcement, state)`` pairs where ``state`` is the subject's
    state row for the announcement's *current* version (None when absent).
    """
    now = as_utc(now) or datetime.now(UTC)
    rows = await public_announcements(db, now=now)
    states = await _states_for(db, subject, rows)

    visible: list[tuple[Announcement, AnnouncementState | None]] = []
    for row in rows:
        state = states.get((row.id, row.version))
        if is_visible(
            display_policy=row.display_policy,
            recur_interval_minutes=row.recur_interval_minutes,
            state=state,
            session_start=subject.session_start,
            now=now,
            is_dismissible=row.is_dismissible,
        ):
            visible.append((row, state))
    return visible


async def upsert_state(
    db: AsyncSession,
    subject: Subject,
    announcement: Announcement,
    *,
    dismissed: bool = False,
    seen: bool = False,
    now: datetime | None = None,
) -> AnnouncementState:
    """Record a dismissal and/or a "seen" marker for one subject."""
    now = as_utc(now) or datetime.now(UTC)
    state = (
        await db.execute(
            select(AnnouncementState).where(
                and_(
                    AnnouncementState.subject_type == subject.subject_type,
                    AnnouncementState.subject_id == subject.subject_id,
                    AnnouncementState.announcement_id == announcement.id,
                    AnnouncementState.announcement_version == announcement.version,
                )
            )
        )
    ).scalars().first()

    if state is None:
        state = AnnouncementState(
            subject_type=subject.subject_type,
            subject_id=subject.subject_id,
            announcement_id=announcement.id,
            announcement_version=announcement.version,
        )
        db.add(state)

    if dismissed:
        state.dismissed_at = now
    if seen:
        state.last_seen_at = now

    await db.flush()
    return state
