"""Per-model overrides service (phase 6, §11.2).

Admin-managed `model_overrides` rows can disable a single (provider, model)
pair. Enforcement is **per-model only**: the provider, other models, the
Model Lab page and stored user configs are never affected. A missing row
means "available" — zero-state parity (B23).

Lookups accept either provider slug or name (mappings and user configs store
either form) and are keyed by every alias, so model listing, routing and
explicit execution all consult the same gate.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import MODEL_OVERRIDE_STATUSES, ModelOverride
from app.services.provider_registry import provider_registry_service


class ModelOverridesService:
    """Default-tolerant reads + transactional admin writes."""

    async def list_rows(
        self, db: AsyncSession, *, provider_slug: str | None = None
    ) -> list[ModelOverride]:
        query = select(ModelOverride).order_by(
            ModelOverride.provider_slug, ModelOverride.model_id
        )
        if provider_slug:
            query = query.where(ModelOverride.provider_slug == provider_slug)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_row(
        self, db: AsyncSession, provider_slug: str, model_id: str
    ) -> ModelOverride | None:
        result = await db.execute(
            select(ModelOverride)
            .where(ModelOverride.provider_slug == provider_slug)
            .where(ModelOverride.model_id == model_id)
        )
        return result.scalars().first()

    async def get_disabled_map(self, db: AsyncSession) -> dict[str, set[str]]:
        """`{provider alias: {disabled model ids}}` for every alias."""
        result = await db.execute(
            select(ModelOverride).where(ModelOverride.status == "disabled")
        )
        disabled: dict[str, set[str]] = {}
        for row in result.scalars().all():
            aliases = {row.provider_slug}
            provider = await provider_registry_service.get_by_slug(
                db, row.provider_slug
            )
            if provider is not None:
                aliases.update({provider.slug, provider.name})
            for alias in aliases:
                disabled.setdefault(alias, set()).add(row.model_id)
        return disabled

    async def is_model_disabled(
        self, db: AsyncSession, provider_identifier: str, model_id: str
    ) -> bool:
        """True when `(provider, model)` is explicitly disabled by an admin."""
        if not provider_identifier or not model_id:
            return False
        aliases = {provider_identifier}
        provider = await provider_registry_service.get_by_identifier(
            db, provider_identifier
        )
        if provider is not None:
            aliases.update({provider.slug, provider.name})
        result = await db.execute(
            select(ModelOverride)
            .where(ModelOverride.provider_slug.in_(aliases))
            .where(ModelOverride.model_id == model_id)
            .where(ModelOverride.status == "disabled")
        )
        return result.scalars().first() is not None

    async def apply(
        self,
        db: AsyncSession,
        *,
        provider_slug: str,
        model_id: str,
        status: str,
        message: str | None = None,
        keep_row: bool = False,
        chat_enabled: bool | None = None,
        review_enabled: bool | None = None,
    ) -> tuple[ModelOverride | None, str]:
        """Upsert or clear one override (no commit).

        `status == "available"` clears the row (restores the model with no
        user action), unless `keep_row` is set: kLLM Cloud keeps an
        `available` row because the row itself is the approval record.
        `chat_enabled`/`review_enabled` are only written when provided, so
        every existing caller keeps today's behaviour. Returns
        `(row_or_None, action)` with action in `{"set", "cleared", "noop"}`;
        raises `ValueError` on bad input.
        """
        if status not in MODEL_OVERRIDE_STATUSES:
            raise ValueError(f"Invalid model override status '{status}'.")

        # Sessions are autoflush=False; make pending writes visible.
        await db.flush()
        result = await db.execute(
            select(ModelOverride)
            .where(ModelOverride.provider_slug == provider_slug)
            .where(ModelOverride.model_id == model_id)
        )
        row = result.scalars().first()

        if status == "available" and not keep_row:
            if row is None:
                return None, "noop"
            await db.delete(row)
            return row, "cleared"

        action = "set"
        if row is None:
            row = ModelOverride(
                provider_slug=provider_slug,
                model_id=model_id,
                status=status,
                message=message,
                chat_enabled=True if chat_enabled is None else bool(chat_enabled),
                review_enabled=(
                    True if review_enabled is None else bool(review_enabled)
                ),
            )
            db.add(row)
        else:
            row.status = status
            row.message = message
            if chat_enabled is not None:
                row.chat_enabled = bool(chat_enabled)
            if review_enabled is not None:
                row.review_enabled = bool(review_enabled)
            db.add(row)
        return row, action

    async def set_surfaces(
        self,
        db: AsyncSession,
        row: ModelOverride,
        *,
        chat_enabled: bool | None = None,
        review_enabled: bool | None = None,
    ) -> ModelOverride:
        """Update the Chat/Review surface flags of an existing row (no commit)."""
        if chat_enabled is not None:
            row.chat_enabled = bool(chat_enabled)
        if review_enabled is not None:
            row.review_enabled = bool(review_enabled)
        db.add(row)
        return row


model_overrides_service = ModelOverridesService()
