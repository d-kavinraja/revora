"""Admin announcement controls (phase 7, §13 / §18).

`GET/POST/PUT/DELETE /admin/announcements` manage the public announcement
feed. Row rules (plan §13, B28): drafts and expired/disabled rows are never
public; schedule, link and copy are validated server-side; publishing is an
explicit state flip. Every mutation writes exactly one audit row (B29), and
announcements never change access controls, feature flags or maintenance
(§12.5 separation) — they are informational copy only.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps_admin import get_current_admin
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.models.admin import AdminUser
from app.models.platform import (
    ANNOUNCEMENT_KINDS,
    ANNOUNCEMENT_STATES,
    Announcement,
)
from app.schemas.admin import (
    AdminAnnouncementCreate,
    AdminAnnouncementRead,
    AdminAnnouncementUpdate,
)
from app.services.admin_audit import admin_audit
from app.services.announcements import (
    MAX_MESSAGE_LEN,
    MAX_TITLE_LEN,
    AnnouncementValidationError,
    sanitize_text,
    validate_link,
    validate_schedule,
)

router = APIRouter()

#: Fields where an explicit `null` means "clear" (everything else ignores
#: `null` so a partial update can never blank a required column).
_CLEARABLE = {"starts_at", "ends_at", "link_url", "link_label"}


def _serialize(row: Announcement) -> AdminAnnouncementRead:
    return AdminAnnouncementRead(
        id=row.id,
        title=row.title,
        message=row.message,
        kind=row.kind,
        state=row.state,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        link_url=row.link_url,
        link_label=row.link_label,
        is_enabled=row.is_enabled,
        is_dismissible=row.is_dismissible,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _bad_request(exc: AnnouncementValidationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
    )


@router.get("/announcements", response_model=list[AdminAnnouncementRead])
async def list_announcements(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Every announcement including drafts/expired (admin only, newest first)."""
    rows = (
        (
            await db.execute(
                select(Announcement).order_by(Announcement.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_serialize(row) for row in rows]


@router.post(
    "/announcements",
    response_model=AdminAnnouncementRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def create_announcement(
    request: Request,
    data: AdminAnnouncementCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Create an announcement in `draft` (never public until published)."""
    if data.kind not in ANNOUNCEMENT_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid kind. Expected one of: "
            + ", ".join(ANNOUNCEMENT_KINDS)
            + ".",
        )
    try:
        title = sanitize_text(
            data.title, field="title", max_length=MAX_TITLE_LEN
        )
        message = sanitize_text(
            data.message, field="message", max_length=MAX_MESSAGE_LEN
        )
        starts_at, ends_at = validate_schedule(data.starts_at, data.ends_at)
        link_url, link_label = validate_link(data.link_url, data.link_label)
    except AnnouncementValidationError as exc:
        raise _bad_request(exc)

    row = Announcement(
        title=title,
        message=message,
        kind=data.kind,
        state="draft",
        starts_at=starts_at,
        ends_at=ends_at,
        link_url=link_url,
        link_label=link_label,
        is_enabled=True if data.is_enabled is None else data.is_enabled,
        is_dismissible=(
            True if data.is_dismissible is None else data.is_dismissible
        ),
        created_by=current_admin.id,
    )
    db.add(row)
    await db.flush()
    await admin_audit(
        db,
        action="admin.announcement_created",
        entity_type="announcement",
        entity_id=str(row.id),
        admin=current_admin,
        request=request,
        details={"title": title, "kind": row.kind, "state": row.state},
        commit=False,
    )
    await db.commit()
    await db.refresh(row)
    return _serialize(row)


@router.put(
    "/announcements/{announcement_id}", response_model=AdminAnnouncementRead
)
@limiter.limit("30/minute")
async def update_announcement(
    request: Request,
    announcement_id: uuid.UUID,
    data: AdminAnnouncementUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Partial update; a `state` flip is audited as publish/unpublish."""
    row = await db.get(Announcement, announcement_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found.",
        )

    patch = data.model_dump(exclude_unset=True)
    effective = {
        key: value
        for key, value in patch.items()
        if value is not None or key in _CLEARABLE
    }
    if not effective:
        return _serialize(row)

    if "kind" in effective and effective["kind"] not in ANNOUNCEMENT_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid kind. Expected one of: "
            + ", ".join(ANNOUNCEMENT_KINDS)
            + ".",
        )
    if "state" in effective and effective["state"] not in ANNOUNCEMENT_STATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state. Expected one of: "
            + ", ".join(ANNOUNCEMENT_STATES)
            + ".",
        )

    try:
        if "title" in effective:
            effective["title"] = sanitize_text(
                effective["title"], field="title", max_length=MAX_TITLE_LEN
            )
        if "message" in effective:
            effective["message"] = sanitize_text(
                effective["message"],
                field="message",
                max_length=MAX_MESSAGE_LEN,
            )
        if "starts_at" in effective or "ends_at" in effective:
            effective["starts_at"], effective["ends_at"] = validate_schedule(
                effective.get("starts_at", row.starts_at),
                effective.get("ends_at", row.ends_at),
            )
        if "link_url" in effective or "link_label" in effective:
            effective["link_url"], effective["link_label"] = validate_link(
                effective.get("link_url", row.link_url),
                effective.get("link_label", row.link_label),
            )
    except AnnouncementValidationError as exc:
        raise _bad_request(exc)

    prior_state = row.state
    for key, value in effective.items():
        setattr(row, key, value)

    if "state" in effective and row.state != prior_state:
        action = (
            "admin.announcement_published"
            if row.state == "published"
            else "admin.announcement_unpublished"
        )
    else:
        action = "admin.announcement_updated"

    await admin_audit(
        db,
        action=action,
        entity_type="announcement",
        entity_id=str(row.id),
        admin=current_admin,
        request=request,
        details={
            "title": row.title,
            "prior_state": prior_state,
            "new_state": row.state,
            "changed": sorted(effective.keys()),
        },
        commit=False,
    )
    await db.commit()
    await db.refresh(row)
    return _serialize(row)


@router.delete(
    "/announcements/{announcement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit("30/minute")
async def delete_announcement(
    request: Request,
    announcement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
):
    """Hard-delete one announcement (audited). 404 when it never existed."""
    row = await db.get(Announcement, announcement_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found.",
        )
    await admin_audit(
        db,
        action="admin.announcement_deleted",
        entity_type="announcement",
        entity_id=str(row.id),
        admin=current_admin,
        request=request,
        details={"title": row.title, "state": row.state},
        commit=False,
    )
    await db.delete(row)
    await db.commit()
