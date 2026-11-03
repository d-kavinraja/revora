"""BotaniQ service: validation + HF delegation + normalization + persistence."""

import logging
import os
import re
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.botaniq import BotaniqInferenceRun
from app.models.user import User
from app.botaniq import dataset as dataset_mod
from app.botaniq.hf_client import (
    BotaniQHFError,
    check_hf_health,
    ensure_hf_ready,
    invalidate_ready_cache,
    run_hf_inference,
)

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

# All image MIME types the service accepts.
EXT_TO_MIME: dict[str, set[str]] = {
    ".jpg":  {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png":  {"image/png"},
    ".webp": {"image/webp"},
    ".avif": {"image/avif"},
    ".gif":  {"image/gif"},
}


def sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "image")
    base = _SAFE_NAME.sub("_", base)[:120] or "image"
    return base


def validate_image(
    filename: str, content_type: str | None, size_bytes: int
) -> tuple[str, str]:
    ext = os.path.splitext(filename.lower())[1]
    allowed = [e.lower() for e in (settings.BOTANIQ_ALLOWED_EXTENSIONS or [])]
    if ext not in allowed:
        raise BotaniQHFError(
            f"Image format is not supported. Supported formats: "
            f"{', '.join(allowed).upper()}",
            kind="unsupported_format",
        )
    max_bytes = int(settings.BOTANIQ_MAX_UPLOAD_MB or 20) * 1024 * 1024
    if size_bytes > max_bytes:
        raise BotaniQHFError(
            f"Image is too large. Maximum size is {settings.BOTANIQ_MAX_UPLOAD_MB} MB.",
            kind="unsupported_format",
        )
    if size_bytes <= 0:
        raise BotaniQHFError("Uploaded image is empty.", kind="unsupported_format")
    canonical = min(EXT_TO_MIME.get(ext, {"image/jpeg"}))
    if content_type:
        ctype = content_type.split(";")[0].strip().lower()
        if ctype in EXT_TO_MIME.get(ext, set()) or ctype == "application/octet-stream":
            canonical = ctype if ctype != "application/octet-stream" else canonical
    return ext, canonical


class BotaniQService:
    async def get_config(self) -> dict[str, Any]:
        return {
            "model": "BotaniQ",
            "model_version": settings.BOTANIQ_MODEL_VERSION,
            "input_resolution": "224x224 RGB",
            "provider": "Hugging Face",
            "compute": "Hosted Inference",
            "max_upload_mb": int(settings.BOTANIQ_MAX_UPLOAD_MB or 20),
            "allowed_extensions": list(settings.BOTANIQ_ALLOWED_EXTENSIONS or []),
        }

    async def get_health(self) -> dict[str, Any]:
        ok, detail = await check_hf_health()
        return {
            "status": "available" if ok else "unavailable",
            "endpoint": settings.MOUTHMAP_HF_ENDPOINT_URL or "",
            "detail": detail,
        }

    async def warm(self) -> dict[str, Any]:
        await ensure_hf_ready()
        return {"status": "ready"}

    def invalidate_ready(self) -> None:
        invalidate_ready_cache()

    def dataset_dir(self) -> str:
        d = settings.BOTANIQ_DATASET_DIR or "app/botaniq/dataset"
        if not os.path.isabs(d):
            here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            cand = os.path.join(os.path.dirname(here), d)
            alt = os.path.join(os.getcwd(), d)
            if os.path.isdir(cand):
                return cand
            return alt
        return d

    async def list_dataset(self) -> list[dict[str, Any]]:
        return dataset_mod.list_sample_images(self.dataset_dir())

    def max_concurrency(self) -> int:
        return max(1, int(settings.BOTANIQ_MAX_CONCURRENT_INFERENCES or 2))

    async def run_inference(
        self,
        db: AsyncSession,
        user: User,
        image_path: str,
        size_bytes: int,
        filename: str,
        content_type: str | None,
        source: str = "upload",
        test_image_id: str | None = None,
    ) -> dict[str, Any]:
        """Run inference on an image already streamed to ``image_path``."""
        safe_name = sanitize_filename(filename)
        ext, canonical = validate_image(safe_name, content_type, size_bytes)
        if ext != os.path.splitext(safe_name.lower())[1]:
            safe_name += ext

        logger.info(
            "botaniq inference started user=%s file=%s bytes=%d source=%s",
            user.id,
            safe_name,
            size_bytes,
            source,
        )
        normalized, raw = await run_hf_inference(image_path, safe_name, canonical)

        prediction = str(normalized.get("prediction") or "")
        top5 = normalized.get("top_5_predictions") or []

        run = BotaniqInferenceRun(
            user_id=user.id,
            image_filename=safe_name,
            image_size_bytes=size_bytes,
            source=source if source in ("test", "upload", "url") else "upload",
            test_image_id=test_image_id,
            prediction=prediction,
            predicted_class=normalized.get("predicted_class"),
            plant_name=normalized.get("plant_name"),
            plant_type=normalized.get("plant_type"),
            confidence=normalized.get("confidence"),
            top_5_predictions=top5,
            inference_time_ms=normalized.get("inference_time_ms"),
            model_version=normalized.get("model_version") or settings.BOTANIQ_MODEL_VERSION,
            status="completed",
            raw_response=raw,
        )
        db.add(run)
        await db.commit()

        return {
            "prediction": prediction,
            "predicted_class": run.predicted_class,
            "plant_name": run.plant_name,
            "plant_type": run.plant_type,
            "confidence": run.confidence,
            "model": "BotaniQ",
            "model_version": run.model_version,
            "classes_available": normalized.get("classes_available"),
            "top_5_predictions": top5,
            "inference_time_ms": run.inference_time_ms,
            "status": "completed",
            "raw": raw if isinstance(raw, dict) else {},
        }

    async def record_failure(
        self,
        db: AsyncSession,
        user: User,
        filename: str,
        size_bytes: int,
        source: str,
        test_image_id: str | None,
        error: str,
    ) -> None:
        try:
            db.add(
                BotaniqInferenceRun(
                    user_id=user.id,
                    image_filename=sanitize_filename(filename),
                    image_size_bytes=size_bytes,
                    source=source if source in ("test", "upload", "url") else "upload",
                    test_image_id=test_image_id,
                    status="failed",
                    error=error[:1000],
                    model_version=settings.BOTANIQ_MODEL_VERSION,
                )
            )
            await db.commit()
        except Exception:
            await db.rollback()

    async def list_history(
        self, db: AsyncSession, user: User, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 20), 100))
        offset = max(0, int(offset or 0))
        res = await db.execute(
            select(BotaniqInferenceRun)
            .where(BotaniqInferenceRun.user_id == user.id)
            .order_by(desc(BotaniqInferenceRun.created_at))
            .limit(limit)
            .offset(offset)
        )
        out = []
        for r in res.scalars().all():
            out.append(
                {
                    "id": str(r.id),
                    "image_filename": r.image_filename,
                    "source": r.source,
                    "test_image_id": r.test_image_id,
                    "prediction": r.prediction,
                    "predicted_class": r.predicted_class,
                    "plant_name": r.plant_name,
                    "plant_type": r.plant_type,
                    "confidence": r.confidence,
                    "top_5_predictions": r.top_5_predictions or [],
                    "inference_time_ms": r.inference_time_ms,
                    "model_version": r.model_version,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return out


botaniq_service = BotaniQService()
