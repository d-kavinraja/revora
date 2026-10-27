"""Public platform status surface (phase 5, §12.4 / §17).

Unauthenticated, maintenance-exempt endpoint that powers the public
`/maintenance` page, the landing/dashboard banners and the edge redirect
in `proxy.ts`. Exposes only user-facing data — never the internal
maintenance reason, admin identity or privileged information.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.platform import FeatureFlag
from app.models.provider import ProviderRegistry
from app.schemas.platform import (
    DisabledProviderRead,
    PublicAnnouncementRead,
    PublicFeatureState,
    PublicMaintenanceState,
    PublicPlatformStatus,
)
from app.services.announcements import public_announcements
from app.services.platform_settings import platform_settings_service, public_state

router = APIRouter()


@router.get("/announcements", response_model=list[PublicAnnouncementRead])
async def get_platform_announcements(db: AsyncSession = Depends(get_db)):
    """Published, enabled, currently-active announcements (§13).

    Server-side filtered (drafts/expired/disabled never leave the backend)
    and ordered newest first. The landing banner degrades gracefully: if
    this endpoint is unreachable the frontend simply renders nothing.
    """
    rows = await public_announcements(db)
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
        )
        for row in rows
    ]


@router.get("/features", response_model=dict[str, PublicFeatureState])
async def get_platform_features(db: AsyncSession = Depends(get_db)):
    """Feature-flag statuses + user-facing messages (dashboard gating, §11.1).

    Default-tolerant: a missing `feature_flags` row means `enabled`, so the
    SQLite `create_all` path matches a fresh seeded deploy.
    """
    flags = await platform_settings_service.get_flags(db)
    return {
        key: PublicFeatureState(status=item["status"], message=item.get("message"))
        for key, item in flags.items()
    }


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
