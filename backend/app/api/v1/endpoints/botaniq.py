"""BotaniQ Model Lab API (inference-only). Thin router → service → HF client."""

import asyncio
import logging
import os
import tempfile

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.deps_flags import require_feature
from app.db.session import get_db
from app.models.user import User
from app.botaniq import dataset as dataset_mod
from app.botaniq.hf_client import BotaniQHFError
from app.botaniq.schemas import (
    BotaniQConfig,
    BotaniQHealth,
    BotaniQWarm,
    HistoryItem,
    InferenceResponse,
    SampleImage,
)
from app.botaniq.service import botaniq_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _hf_error_to_http(exc: BotaniQHFError) -> HTTPException:
    if exc.kind == "unsupported_format":
        msg = str(exc)
        status = 413 if "too large" in msg.lower() else 422
        return HTTPException(status_code=status, detail=msg)
    if exc.kind == "failed":
        return HTTPException(status_code=422, detail=str(exc))
    if exc.kind == "timeout":
        return HTTPException(
            status_code=504, detail="Inference timed out. Please try again."
        )
    if exc.kind == "waking_timeout":
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(
        status_code=502,
        detail="BotaniQ inference service is currently unavailable.",
    )


_inference_semaphore: asyncio.Semaphore | None = None
_inference_semaphore_size = 0


def _inference_slot() -> asyncio.Semaphore:
    global _inference_semaphore, _inference_semaphore_size
    want = max(1, int(settings.BOTANIQ_MAX_CONCURRENT_INFERENCES or 2))
    if _inference_semaphore is None or _inference_semaphore_size != want:
        _inference_semaphore = asyncio.Semaphore(want)
        _inference_semaphore_size = want
    return _inference_semaphore


@router.get("/config", response_model=BotaniQConfig)
async def get_config(
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("botaniq")),
):
    return await botaniq_service.get_config()


@router.get("/health", response_model=BotaniQHealth)
async def get_health(
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("botaniq")),
):
    return await botaniq_service.get_health()


@router.post("/warm", response_model=BotaniQWarm)
async def warm_model(
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("botaniq")),
):
    """Wake the shared HF Space and confirm readiness (bounded).

    BotaniQ shares the Space with MouthMap; a warm MouthMap Space means
    BotaniQ is also ready. On-demand only — page loads never wake the model.
    """
    try:
        return await botaniq_service.warm()
    except BotaniQHFError as exc:
        raise _hf_error_to_http(exc) from exc


@router.get("/dataset", response_model=list[SampleImage])
async def list_dataset(
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("botaniq")),
):
    return await botaniq_service.list_dataset()


@router.get("/dataset/{image_id}/stream")
async def stream_dataset_image(
    image_id: str,
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("botaniq")),
):
    match = dataset_mod.resolve_sample_image(botaniq_service.dataset_dir(), image_id)
    if not match or not os.path.isfile(match["abs_path"]):
        raise HTTPException(status_code=404, detail="Sample image not found")
    ext = os.path.splitext(match["filename"].lower())[1].lstrip(".")
    media_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "webp": "image/webp", "avif": "image/avif", "gif": "image/gif",
    }
    media = media_map.get(ext, "image/jpeg")
    return FileResponse(match["abs_path"], media_type=media, filename=match["filename"])


@router.post("/inference/url", response_model=InferenceResponse)
async def run_inference_url(
    image_url: str = Form(...),
    test_image_id: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("botaniq")),
):
    """Fetch a public image URL and classify it.

    The backend fetches the URL server-side (no CORS issues). Only http/https
    schemes are permitted. On fetch failure the user receives an actionable
    422 rather than a generic 502.
    """
    if not image_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Only http and https URLs are supported.")

    slot = _inference_slot()
    if slot.locked():
        raise HTTPException(
            status_code=429,
            detail="Inference is busy. Please wait a moment and try again.",
        )

    tmp_path: str | None = None
    try:
        max_bytes = int(settings.BOTANIQ_MAX_UPLOAD_MB or 20) * 1024 * 1024
        chunk_size = 64 * 1024
        size_bytes = 0
        # Derive a safe filename from the URL path.
        url_stem = image_url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or "image"
        ext = os.path.splitext(url_stem.lower())[1]
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"):
            ext = ".jpg"  # fallback; MIME will override

        fd, tmp_path = tempfile.mkstemp(prefix="botaniq_url_", suffix=ext)
        content_type: str | None = None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
                async with client.stream("GET", image_url, follow_redirects=True) as resp:
                    if resp.status_code >= 400:
                        raise BotaniQHFError(
                            f"Could not fetch image: HTTP {resp.status_code}. "
                            "Check the URL and ensure the image is publicly accessible.",
                            kind="unsupported_format",
                        )
                    content_type = resp.headers.get("content-type", "").split(";")[0].strip() or None
                    with os.fdopen(fd, "wb") as fh:
                        async for chunk in resp.aiter_bytes(chunk_size):
                            size_bytes += len(chunk)
                            if size_bytes > max_bytes:
                                raise BotaniQHFError(
                                    f"Image from URL is too large. Maximum is "
                                    f"{settings.BOTANIQ_MAX_UPLOAD_MB} MB.",
                                    kind="unsupported_format",
                                )
                            await asyncio.to_thread(fh.write, chunk)
        except httpx.HTTPError as exc:
            raise BotaniQHFError(
                "Could not fetch image from the provided URL. "
                "Ensure the URL is publicly accessible and points to an image.",
                kind="unsupported_format",
            ) from exc

        filename = url_stem or "image.jpg"
        try:
            await botaniq_service.warm()

            async def _run_once():
                async with slot:
                    return await botaniq_service.run_inference(
                        db, current_user,
                        image_path=tmp_path,
                        size_bytes=size_bytes,
                        filename=filename,
                        content_type=content_type,
                        source="url",
                        test_image_id=test_image_id,
                    )

            try:
                return await _run_once()
            except BotaniQHFError as exc:
                if exc.accepted:
                    raise
                botaniq_service.invalidate_ready()
                await botaniq_service.warm()
                return await _run_once()
        except BotaniQHFError as exc:
            logger.warning("botaniq url-inference failed: %s", exc.kind)
            await botaniq_service.record_failure(
                db, current_user, filename, size_bytes, "url", test_image_id, str(exc)
            )
            raise _hf_error_to_http(exc)
    except BotaniQHFError as exc:
        if "too large" in str(exc).lower():
            try:
                await botaniq_service.record_failure(
                    db, current_user, image_url[:255], size_bytes if 'size_bytes' in dir() else 0,  # type: ignore[name-defined]
                    "url", test_image_id, str(exc)
                )
            except Exception:
                pass
        raise _hf_error_to_http(exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.post("/inference", response_model=InferenceResponse)
async def run_inference(
    image: UploadFile = File(...),
    test_image_id: str | None = Form(default=None),
    source: str = Form(default="upload"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("botaniq")),
):
    slot = _inference_slot()
    if slot.locked():
        raise HTTPException(
            status_code=429,
            detail="Inference is busy. Please wait a moment and try again.",
        )

    chunk_size = max(64 * 1024, int(settings.BOTANIQ_STREAM_CHUNK_BYTES or 512 * 1024))
    max_bytes = int(settings.BOTANIQ_MAX_UPLOAD_MB or 20) * 1024 * 1024
    filename = image.filename or "image"
    content_type = image.content_type
    tmp_path: str | None = None
    size_bytes = 0
    try:
        ext = os.path.splitext((filename or "image").lower())[1]
        fd, tmp_path = tempfile.mkstemp(prefix="botaniq_up_", suffix=ext or ".bin")
        with os.fdopen(fd, "wb") as fh:
            while True:
                chunk = await image.read(chunk_size)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise BotaniQHFError(
                        f"Image is too large. Maximum size is "
                        f"{settings.BOTANIQ_MAX_UPLOAD_MB} MB.",
                        kind="unsupported_format",
                    )
                await asyncio.to_thread(fh.write, chunk)
                await asyncio.to_thread(fh.flush)
        try:
            await botaniq_service.warm()

            async def _run_once():
                async with slot:
                    return await botaniq_service.run_inference(
                        db, current_user,
                        image_path=tmp_path,
                        size_bytes=size_bytes,
                        filename=filename,
                        content_type=content_type,
                        source=source,
                        test_image_id=test_image_id,
                    )

            try:
                return await _run_once()
            except BotaniQHFError as exc:
                if exc.accepted:
                    raise
                logger.warning(
                    "botaniq inference failed before acceptance (%s); re-warming once",
                    exc.kind,
                )
                botaniq_service.invalidate_ready()
                await botaniq_service.warm()
                return await _run_once()
        except BotaniQHFError as exc:
            logger.warning("botaniq inference failed: %s", exc.kind)
            await botaniq_service.record_failure(
                db, current_user, filename, size_bytes, source, test_image_id, str(exc)
            )
            raise _hf_error_to_http(exc)
    except BotaniQHFError as exc:
        if "too large" in str(exc).lower():
            try:
                await botaniq_service.record_failure(
                    db, current_user, filename, size_bytes, source, test_image_id, str(exc)
                )
            except Exception:
                pass
        raise _hf_error_to_http(exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.get("/history", response_model=list[HistoryItem])
async def list_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_feature("botaniq")),
):
    return await botaniq_service.list_history(db, current_user, limit, offset)
