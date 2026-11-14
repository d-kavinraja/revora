"""Public platform status surface (phase 5, §12.4 / §17).

Unauthenticated, maintenance-exempt endpoint that powers the public
`/maintenance` page, the landing/dashboard banners and the edge redirect
in `proxy.ts`. Exposes only user-facing data — never the internal
maintenance reason, admin identity or privileged information.

The announcement feed (§13) is resolved per *subject*: a signed-in user
when a valid session cookie is present, otherwise the anonymous browser
device. Dismissals never leak across subjects, and a published-content
update (version bump) makes an announcement eligible again for subjects
that dismissed the previous version.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_optional_session
from app.db.session import get_db
from app.models.platform import Announcement, FeatureFlag
from app.models.provider import ProviderRegistry
from app.models.user import User
from app.schemas.platform import (
    DisabledProviderRead,
    PublicAnnouncementRead,
    PublicFeatureState,
    PublicMaintenanceState,
    PublicPlatformStatus,
)
from app.services.announcements import (
    DEVICE_COOKIE_NAME,
    DEVICE_SINCE_COOKIE_NAME,
    Subject,
    as_utc,
    device_subject,
    normalize_device_id,
    upsert_state,
    user_subject,
    visible_announcements,
)
from app.services.platform_settings import platform_settings_service, public_state

router = APIRouter()


@router.get("/usage-analytics")
async def get_usage_analytics_status(db: AsyncSession = Depends(get_db)):
    enabled = await platform_settings_service.is_usage_analytics_enabled(db)
    return {"enabled": enabled}


def _device_id_from(request: Request) -> str | None:
    """Resolve the anonymous device id (header wins over cookie)."""
    header_id = normalize_device_id(request.headers.get("x-announcement-device-id"))
    if header_id:
        return header_id
    return normalize_device_id(request.cookies.get(DEVICE_COOKIE_NAME))


def _device_since_from(request: Request) -> datetime | None:
    raw = request.cookies.get(DEVICE_SINCE_COOKIE_NAME)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def _resolve_subject(
    request: Request,
    db: AsyncSession,
    user: User | None,
    payload: dict | None = None,
) -> Subject:
    """Pick the subject a request's dismissal state belongs to."""
    if user is not None:
        # The token's `iat` is the moment this login session started: it is
        # stable for the whole session and changes on the next login, which
        # is exactly the boundary the `every_login` policy needs.
        issued_at = None
        if payload:
            raw_iat = payload.get("iat")
            if raw_iat is not None:
                try:
                    issued_at = datetime.fromtimestamp(int(raw_iat), tz=UTC)
                except (TypeError, ValueError, OSError):
                    issued_at = None
        if issued_at is None:
            issued_at = as_utc(getattr(user, "last_login_at", None))
        return user_subject(user.id, issued_at)

    device_id = _device_id_from(request)
    if device_id is None:
        # No device id and no session: fall back to a stable per-request
        # anonymous subject so the feed still works (nothing is persisted
        # against it).
        device_id = "anonymous"
    return device_subject(device_id, _device_since_from(request))


def _ensure_device_cookies(request: Request, response: Response) -> str | None:
    """Return the device id, setting the device cookies when missing."""
    device_id = _device_id_from(request)
    if device_id is None:
        device_id = str(uuid.uuid4())
        response.set_cookie(
            key=DEVICE_COOKIE_NAME,
            value=device_id,
            httponly=False,  # not a credential; the SPA may read it
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
            max_age=60 * 60 * 24 * 365,
        )
    if request.cookies.get(DEVICE_SINCE_COOKIE_NAME) is None:
        response.set_cookie(
            key=DEVICE_SINCE_COOKIE_NAME,
            value=datetime.now(UTC).isoformat(),
            httponly=False,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
            max_age=60 * 60 * 24 * 365,
        )
    return device_id


@router.get("/announcements", response_model=list[PublicAnnouncementRead])
async def get_platform_announcements(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    session: tuple[User | None, dict] = Depends(get_optional_session),
):
    """Published, enabled, currently-active announcements (§13).

    Server-side filtered (drafts/expired/disabled never leave the backend),
    ordered newest first, and resolved for the calling subject so a
    dismissed announcement is not returned to the user who dismissed it.
    The landing banner degrades gracefully: if this endpoint is unreachable
    the frontend simply renders nothing.
    """
    _ensure_device_cookies(request, response)

    subject = await _resolve_subject(request, db, session[0], session[1])
    now = datetime.now(UTC)
    rows = await visible_announcements(db, subject, now=now)

    return [
        PublicAnnouncementRead(
            id=row.id,
            title=row.title,
            message=row.message,
            kind=row.kind,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            link_url=row.link_url,
            link_label=row.link_label,
            is_dismissible=row.is_dismissible,
            version=row.version,
            display_policy=row.display_policy,
            recur_interval_minutes=row.recur_interval_minutes,
            audience=row.audience,
            dismissed=False,
        )
        for row, _state in rows
    ]


@router.post("/announcements/{announcement_id}/dismiss")
async def dismiss_platform_announcement(
    announcement_id: uuid.UUID,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    session: tuple[User | None, dict] = Depends(get_optional_session),
):
    """Dismiss one announcement for the calling subject.

    Idempotent. The dismissal is scoped to the subject (user or device)
    and to the announcement's current version, so an updated announcement
    becomes eligible again.
    """
    _ensure_device_cookies(request, response)

    announcement = await db.get(Announcement, announcement_id)
    if announcement is None:
        return Response(status_code=204)

    now = datetime.now(UTC)
    if not announcement.is_dismissible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Announcement is not dismissible.",
        )
    if (
        announcement.state != "published"
        or not announcement.is_enabled
        or (announcement.starts_at is not None and announcement.starts_at > now)
        or (announcement.ends_at is not None and announcement.ends_at <= now)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Announcement is not active.",
        )

    subject = await _resolve_subject(request, db, session[0], session[1])
    await upsert_state(db, subject, announcement, dismissed=True)
    await db.commit()

    return {"status": "dismissed", "id": str(announcement.id)}


@router.post("/announcements/{announcement_id}/seen")
async def mark_platform_announcement_seen(
    announcement_id: uuid.UUID,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    session: tuple[User | None, dict] = Depends(get_optional_session),
):
    """Record that the calling subject has seen one announcement.

    Used by the ``every_login`` policy so the same announcement is not
    displayed repeatedly within one login session.
    """
    _ensure_device_cookies(request, response)

    announcement = await db.get(Announcement, announcement_id)
    if announcement is None:
        return Response(status_code=204)

    now = datetime.now(UTC)
    # Non-dismissible announcements stay visible regardless of seen state, so
    # recording a seen marker would only create stale state.
    if (
        not announcement.is_dismissible
        or announcement.state != "published"
        or not announcement.is_enabled
        or (announcement.starts_at is not None and announcement.starts_at > now)
        or (announcement.ends_at is not None and announcement.ends_at <= now)
    ):
        return Response(status_code=204)

    subject = await _resolve_subject(request, db, session[0], session[1])
    await upsert_state(db, subject, announcement, seen=True)
    await db.commit()

    return {"status": "seen", "id": str(announcement.id)}


@router.get("/features", response_model=dict[str, PublicFeatureState])
async def get_platform_features(db: AsyncSession = Depends(get_db)):
    """Feature-flag statuses + user-facing messages (dashboard gating, §11.1).

    Default-tolerant: a missing `feature_flags` row means `enabled`, so the
    SQLite `create_all` path matches a fresh seeded deploy.
    """
    flags = await platform_settings_service.get_flags(db)
    result: dict[str, PublicFeatureState] = {}
    for key, item in flags.items():
        result[key] = PublicFeatureState(
            status=item["status"], message=item.get("message")
        )
    return result


@router.get("/status", response_model=PublicPlatformStatus)
async def get_platform_status(db: AsyncSession = Depends(get_db)):
    """Current maintenance state, feature flags and blocked providers."""
    maintenance = await platform_settings_service.get_maintenance(db)

    flags = (await db.execute(select(FeatureFlag))).scalars().all()
    features = {flag.key: flag.status for flag in flags}

    blocked = (
        (
            await db.execute(
                select(ProviderRegistry).where(
                    or_(
                        ProviderRegistry.is_enabled == False,
                        ProviderRegistry.status != "available",
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    disabled_providers = [
        DisabledProviderRead(
            slug=provider.slug,
            message=provider.status_message,
            expires_at=provider.status_expires_at,
        )
        for provider in blocked
    ]

    return PublicPlatformStatus(
        maintenance=PublicMaintenanceState(**public_state(maintenance)),
        features=features,
        disabled_providers=disabled_providers,
    )
