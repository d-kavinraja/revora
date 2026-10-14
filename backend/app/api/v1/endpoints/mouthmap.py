"""MouthMap Model Lab API (inference-only). Thin router -> service -> HF client."""

import asyncio
import logging
import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.mouthmap import dataset as dataset_mod
from app.mouthmap.hf_client import MouthMapHFError
from app.mouthmap.schemas import (
    HistoryItem,
    InferenceResponse,
    MouthMapConfig,
    MouthMapHealth,
    TestVideo,
)
from app.mouthmap.service import mouthmap_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _hf_error_to_http(exc: MouthMapHFError) -> HTTPException:
    if exc.kind == "unsupported_format":
        msg = str(exc)
        status = 413 if "too large" in msg.lower() else 422
        return HTTPException(status_code=status, detail=msg)
    if exc.kind == "failed":
        # The Space rejected the video content itself (invalid/incomplete/
        # unsupported). Pass its safe validation message through so the
        # user knows the upload — not the service — is the problem.
        return HTTPException(status_code=422, detail=str(exc))
    if exc.kind == "timeout":
        return HTTPException(
            status_code=504, detail="Inference timed out. Please try again."
        )
    return HTTPException(
        status_code=502,
        detail="MouthMap inference service is currently unavailable.",
    )

_inference_semaphore: asyncio.Semaphore | None = None
_inference_semaphore_size = 0


def _inference_slot() -> asyncio.Semaphore:
    """Process-wide inference gate sized by current settings.

    Rebuilt if the configured concurrency changes (tests, reloads).
    """
    global _inference_semaphore, _inference_semaphore_size
    want = max(1, int(settings.MOUTHMAP_MAX_CONCURRENT_INFERENCES or 1))
    if _inference_semaphore is None or _inference_semaphore_size != want:
        _inference_semaphore = asyncio.Semaphore(want)
        _inference_semaphore_size = want
    return _inference_semaphore



@router.get("/config", response_model=MouthMapConfig)
async def get_config(current_user: User = Depends(get_current_user)):
    return await mouthmap_service.get_config()


@router.get("/health", response_model=MouthMapHealth)
async def get_health(current_user: User = Depends(get_current_user)):
    return await mouthmap_service.get_health()


@router.get("/dataset", response_model=list[TestVideo])
async def list_dataset(current_user: User = Depends(get_current_user)):
    return await mouthmap_service.list_dataset()


@router.get("/dataset/{video_id}/stream")
async def stream_dataset_video(
    video_id: str,
    current_user: User = Depends(get_current_user),
):
    match = dataset_mod.resolve_test_video(mouthmap_service.dataset_dir(), video_id)
    if not match or not os.path.isfile(match["abs_path"]):
        raise HTTPException(status_code=404, detail="Test video not found")
    ext = os.path.splitext(match["filename"].lower())[1]
    media = {"mp4": "video/mp4", "webm": "video/webm", "mpg": "video/mpeg"}.get(
        ext.lstrip("."), "video/mp4"
    )
    return FileResponse(match["abs_path"], media_type=media, filename=match["filename"])


@router.post("/inference", response_model=InferenceResponse)
async def run_inference(
    video: UploadFile = File(...),
    test_video_id: str | None = Form(default=None),
    source: str = Form(default="upload"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Concurrency gate: one inference at a time on small instances.
    # Extra callers get an instant 429 instead of stacking 180s workers.
    slot = _inference_slot()
    if slot.locked():
        raise HTTPException(
            status_code=429,
            detail="Inference is busy. Please wait a moment and try again.",
        )

    # Stream the upload to disk in small chunks with a hard byte cap.
    # Peak RAM stays at one chunk (~1MB) regardless of upload size.
    chunk_size = max(64 * 1024, int(settings.MOUTHMAP_STREAM_CHUNK_BYTES or 1024 * 1024))
    max_bytes = int(settings.MOUTHMAP_MAX_UPLOAD_MB or 50) * 1024 * 1024
    filename = video.filename or "video"
    content_type = video.content_type
    tmp_path: str | None = None
    size_bytes = 0
    try:
        ext = os.path.splitext((filename or "video").lower())[1]
        fd, tmp_path = tempfile.mkstemp(prefix="mouthmap_up_", suffix=ext or ".bin")
        with os.fdopen(fd, "wb") as fh:
            while True:
                chunk = await video.read(chunk_size)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise MouthMapHFError(
                        f"Video is too large. Maximum size is "
                        f"{settings.MOUTHMAP_MAX_UPLOAD_MB} MB.",
                        kind="unsupported_format",
                    )
                # Blocking disk write must not stall the event loop.
                await asyncio.to_thread(fh.write, chunk)
                await asyncio.to_thread(fh.flush)
        try:
            async with slot:
                return await mouthmap_service.run_inference(
                    db,
                    current_user,
                    video_path=tmp_path,
                    size_bytes=size_bytes,
                    filename=filename,
                    content_type=content_type,
                    source=source,
                    test_video_id=test_video_id,
                )
        except MouthMapHFError as exc:
            logger.warning("mouthmap inference failed: %s", exc.kind)
            await mouthmap_service.record_failure(
                db,
                current_user,
                filename,
                size_bytes,
                source,
                test_video_id,
                str(exc),
            )
            raise _hf_error_to_http(exc)
    except MouthMapHFError as exc:
        # Size-cap violations raised during streaming: record + map.
        if "too large" in str(exc).lower():
            try:
                await mouthmap_service.record_failure(
                    db, current_user, filename, size_bytes, source, test_video_id, str(exc)
                )
            except Exception:
                pass
        raise _hf_error_to_http(exc)
    finally:
        # The service never takes ownership of the staged file: always clean up.
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
):
    return await mouthmap_service.list_history(db, current_user, limit, offset)
