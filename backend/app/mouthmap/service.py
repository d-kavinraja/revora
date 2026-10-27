"""MouthMap service: validation + HF delegation + normalization + persistence."""

import logging
import os
import re
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.mouthmap import MouthmapInferenceRun
from app.models.user import User
from app.mouthmap import dataset as dataset_mod
from app.mouthmap.hf_client import (
    MouthMapHFError,
    check_hf_health,
    ensure_hf_ready,
    invalidate_ready_cache,
    run_hf_inference,
)

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

EXT_TO_MIME = {
    ".mp4": {"video/mp4", "application/mp4"},
    ".webm": {"video/webm"},
    ".mpg": {"video/mpeg", "video/mpg", "video/x-mpg"},
}


def sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "video")
    base = _SAFE_NAME.sub("_", base)[:120] or "video"
    return base


def validate_video(
    filename: str, content_type: str | None, size_bytes: int
) -> tuple[str, str]:
    ext = os.path.splitext(filename.lower())[1]
    allowed = [e.lower() for e in (settings.MOUTHMAP_ALLOWED_EXTENSIONS or [])]
    if ext not in allowed:
        raise MouthMapHFError(
            f"Video format is not supported. Supported formats: "
            f"{', '.join(allowed).upper()}",
            kind="unsupported_format",
        )
    max_bytes = int(settings.MOUTHMAP_MAX_UPLOAD_MB or 50) * 1024 * 1024
    if size_bytes > max_bytes:
        raise MouthMapHFError(
            f"Video is too large. Maximum size is {settings.MOUTHMAP_MAX_UPLOAD_MB} MB.",
            kind="unsupported_format",
        )
    if size_bytes <= 0:
        raise MouthMapHFError("Uploaded video is empty.", kind="unsupported_format")
    # Do not trust client MIME alone: accept if it matches the extension family,
    # else fall back to the canonical MIME for the extension.
    canonical = min(EXT_TO_MIME.get(ext, {"video/mp4"}))
    if content_type:
        ctype = content_type.split(";")[0].strip().lower()
        if ctype in EXT_TO_MIME.get(ext, set()) or ctype == "application/octet-stream":
            canonical = ctype if ctype != "application/octet-stream" else canonical
    return ext, canonical


def _norm_text(s: str | None) -> str | None:
    if s is None:
        return None
    return " ".join(str(s).strip().split()) or None


class MouthMapService:
    async def get_config(self) -> dict[str, Any]:
        return {
            "model": "MouthMap",
            "model_version": settings.MOUTHMAP_MODEL_VERSION,
            "input_frames": 75,
            "input_resolution": "46x140 grayscale",
            "provider": "Hugging Face",
            "compute": "Hosted Inference",
            "max_upload_mb": int(settings.MOUTHMAP_MAX_UPLOAD_MB or 50),
            "allowed_extensions": list(settings.MOUTHMAP_ALLOWED_EXTENSIONS or []),
        }

    async def get_health(self) -> dict[str, Any]:
        ok, detail = await check_hf_health()
        return {
            "status": "available" if ok else "unavailable",
            # Schema requires `endpoint: str`; coalesce None so an
            # unconfigured endpoint degrades to "" instead of a 500.
            "endpoint": settings.MOUTHMAP_HF_ENDPOINT_URL or "",
            "detail": detail,
        }

    async def warm(self) -> dict[str, Any]:
        """Wake the HF Space (bounded) and confirm it is serving.

        Delegates to the single-flight readiness routine in the HF client, so
        concurrent callers share one wake cycle and a recent success is cached.
        """
        await ensure_hf_ready()
        return {"status": "ready"}

    def invalidate_ready(self) -> None:
        """Drop the cached 'ready' verdict so the next run re-probes the Space."""
        invalidate_ready_cache()

    def dataset_dir(self) -> str:
        d = settings.MOUTHMAP_DATASET_DIR or "app/mouthmap/dataset"
        if not os.path.isabs(d):
            # Resolve relative to backend/ working dir
            here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            cand = os.path.join(os.path.dirname(here), d)
            alt = os.path.join(os.getcwd(), d)
            if os.path.isdir(cand):
                return cand
            return alt
        return d

    async def list_dataset(self) -> list[dict[str, Any]]:
        return dataset_mod.list_test_videos(self.dataset_dir())

    def max_concurrency(self) -> int:
        return max(1, int(settings.MOUTHMAP_MAX_CONCURRENT_INFERENCES or 1))

    async def run_inference(
        self,
        db: AsyncSession,
        user: User,
        video_path: str,
        size_bytes: int,
        filename: str,
        content_type: str | None,
        source: str = "upload",
        test_video_id: str | None = None,
    ) -> dict[str, Any]:
        """Run inference on a video already streamed to ``video_path``.

        The file must already satisfy the size cap — it was enforced while
        streaming (endpoint), so only name/MIME checks run here. The file
        is NEVER fully read into memory: the HF upload streams from disk.
        """
        safe_name = sanitize_filename(filename)
        ext, canonical = validate_video(safe_name, content_type, size_bytes)
        if ext != os.path.splitext(safe_name.lower())[1]:
            safe_name += ext

        expected: str | None = None
        if test_video_id:
            match = dataset_mod.resolve_test_video(self.dataset_dir(), test_video_id)
            if match:
                expected = _norm_text(match.get("ground_truth"))

        logger.info(
            "mouthmap inference started user=%s file=%s bytes=%d source=%s",
            user.id,
            safe_name,
            size_bytes,
            source,
        )
        normalized, raw = await run_hf_inference(video_path, safe_name, canonical)

        prediction = _norm_text(normalized.get("prediction")) or ""
        is_match = (
            (
                _norm_text(expected) is not None
                and _norm_text(prediction) is not None
                and _norm_text(prediction).lower() == _norm_text(expected).lower()
            )
            if expected
            else None
        )

        run = MouthmapInferenceRun(
            user_id=user.id,
            video_filename=safe_name,
            video_size_bytes=size_bytes,
            source=source if source in ("test", "upload", "record") else "upload",
            test_video_id=test_video_id,
            prediction=prediction,
            expected=_norm_text(expected),
            is_match=is_match,
            confidence=normalized.get("confidence"),
            inference_time_ms=normalized.get("inference_time_ms"),
            frames_processed=normalized.get("frames_processed"),
            model_version=normalized.get("model_version")
            or settings.MOUTHMAP_MODEL_VERSION,
            status="completed",
            raw_response=raw,
        )
        db.add(run)
        await db.commit()

        return {
            "prediction": prediction,
            "model": "MouthMap",
            "model_version": run.model_version,
            "confidence": run.confidence,
            "inference_time_ms": run.inference_time_ms,
            "frames_processed": run.frames_processed,
            "status": "completed",
            "expected": run.expected,
            "is_match": run.is_match,
            "raw": raw if isinstance(raw, dict) else {},
        }

    async def record_failure(
        self,
        db: AsyncSession,
        user: User,
        filename: str,
        size_bytes: int,
        source: str,
        test_video_id: str | None,
        error: str,
    ) -> None:
        try:
            db.add(
                MouthmapInferenceRun(
                    user_id=user.id,
                    video_filename=sanitize_filename(filename),
                    video_size_bytes=size_bytes,
                    source=source
                    if source in ("test", "upload", "record")
                    else "upload",
                    test_video_id=test_video_id,
                    status="failed",
                    error=error[:1000],
                    model_version=settings.MOUTHMAP_MODEL_VERSION,
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
            select(MouthmapInferenceRun)
            .where(MouthmapInferenceRun.user_id == user.id)
            .order_by(desc(MouthmapInferenceRun.created_at))
            .limit(limit)
            .offset(offset)
        )
        out = []
        for r in res.scalars().all():
            out.append(
                {
                    "id": str(r.id),
                    "video_filename": r.video_filename,
                    "source": r.source,
                    "test_video_id": r.test_video_id,
                    "prediction": r.prediction,
                    "expected": r.expected,
                    "is_match": r.is_match,
                    "confidence": r.confidence,
                    "inference_time_ms": r.inference_time_ms,
                    "frames_processed": r.frames_processed,
                    "model_version": r.model_version,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return out


mouthmap_service = MouthMapService()
