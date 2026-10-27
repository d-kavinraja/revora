"""Hugging Face Gradio client for the hosted MouthMap inference Space.

Actual discovered contract (verified live against the configured Space):
  1. POST {base}/gradio_api/upload (multipart, field "files") -> [server_path]
  2. POST {base}/gradio_api/call/v2/predict
     {"video": {"path": server_path, "meta": {"_type": "gradio.FileData"}}}
     -> {"event_id": "..."}
  3. GET {base}/gradio_api/call/predict/{event_id} (SSE)
     -> "event: complete\\ndata: [{...}]"

The Space is private. The server-side MOUTHMAP_HF_API_TOKEN is sent as
Bearer on every Space call. The endpoint URL itself is configuration
(Render env in prod, backend/.env locally) and is never hardcoded.
"""

import asyncio
import json
import logging
import os
import time

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_FILEDATA_META = {"_type": "gradio.FileData"}


class MouthMapHFError(Exception):
    def __init__(
        self, message: str, kind: str = "unavailable", *, accepted: bool = False
    ):
        super().__init__(message)
        # unsupported_format | timeout | unavailable | malformed | failed | waking_timeout
        self.kind = kind
        # True once the Space has taken ownership of the inference request (an
        # event_id was issued). A failure after this point may already be
        # executing on the Space, so callers must NOT retry it.
        self.accepted = accepted


def _base_url() -> str:
    return (settings.MOUTHMAP_HF_ENDPOINT_URL or "").rstrip("/")


def _auth_headers() -> dict[str, str]:
    if settings.MOUTHMAP_HF_API_TOKEN:
        return {"Authorization": f"Bearer {settings.MOUTHMAP_HF_API_TOKEN}"}
    return {}


def _pick_first(d: dict, keys: list[str]):
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def _pick_timing(result: dict):
    """Pick the real model inference time in ms.

    Priority order:
      1. raw["timing"]["inference_ms"] (the Space's measured model
         inference time — this is what the UI "Inference Time" must show);
      2. legacy flat keys (back-compat with other response shapes).
    The client round-trip elapsed time stays the final fallback and is
    applied by the caller only when nothing above exists.
    """
    timing = result.get("timing")
    if isinstance(timing, dict):
        v = timing.get("inference_ms")
        if v is not None and v != "":
            return v
    return _pick_first(
        result, ["inference_time_ms", "inference_time", "elapsed_ms", "duration_ms"]
    )


def normalize_hf_result(result: dict) -> dict:
    """Normalize the raw HF result dict into the stable Revora contract.

    Only populates fields that genuinely exist — never fabricates metrics.
    """
    prediction = _pick_first(
        result, ["prediction", "predicted_sentence", "sentence", "text", "transcript"]
    )
    if prediction is None:
        raise MouthMapHFError(
            f"Unexpected inference response shape: {sorted(result.keys())}",
            kind="malformed",
        )
    out: dict = {
        "prediction": str(prediction),
        "model_version": _pick_first(result, ["model_version", "version"]),
        "confidence": _pick_first(result, ["confidence", "score"]),
        "inference_time_ms": _pick_timing(result),
        "frames_processed": _pick_first(
            result, ["frames_processed", "num_frames", "frames"]
        ),
    }
    # Coerce numerics safely; leave None when absent/invalid.
    try:
        out["confidence"] = (
            float(out["confidence"]) if out["confidence"] is not None else None
        )
    except (TypeError, ValueError):
        out["confidence"] = None
    try:
        out["inference_time_ms"] = (
            int(float(out["inference_time_ms"]))
            if out["inference_time_ms"] is not None
            else None
        )
    except (TypeError, ValueError):
        out["inference_time_ms"] = None
    try:
        out["frames_processed"] = (
            int(out["frames_processed"])
            if out["frames_processed"] is not None
            else None
        )
    except (TypeError, ValueError):
        out["frames_processed"] = None
    return out


def _parse_sse_payload(body: str) -> dict:
    """Extract the final `data:` JSON array from the SSE stream."""
    data_lines = [
        line[5:].strip() for line in body.splitlines() if line.startswith("data:")
    ]
    if not data_lines:
        raise MouthMapHFError("Empty inference event stream", kind="malformed")
    try:
        payload = json.loads(data_lines[-1])
    except json.JSONDecodeError as exc:
        raise MouthMapHFError(
            "Malformed inference event stream", kind="malformed"
        ) from exc
    if not isinstance(payload, list) or not payload:
        raise MouthMapHFError("Unexpected inference payload shape", kind="malformed")
    first = payload[0]
    if isinstance(first, dict) and first.get("status") == "failed":
        # Surface the Space's own validation message (safe, user-actionable
        # strings such as "Uploaded video is invalid, incomplete, or
        # unsupported."). Never includes tokens, paths, or video bytes.
        raise MouthMapHFError(
            str(first.get("error") or "MouthMap inference failed"), kind="failed"
        )
    if not isinstance(first, dict):
        raise MouthMapHFError("Unexpected inference payload shape", kind="malformed")
    return first


async def run_hf_inference(
    video_path: str, filename: str, content_type: str
) -> tuple[dict, dict]:
    """Upload video to the HF Space and run /predict. Returns (normalized, raw).

    The video streams from ``video_path`` on disk and is never loaded into
    memory — critical on small instances (Render Free 512MB).
    """
    base = _base_url()
    if not base:
        raise MouthMapHFError("MouthMap endpoint is not configured", kind="unavailable")
    try:
        size_bytes = os.path.getsize(video_path)
    except OSError as exc:
        raise MouthMapHFError("Uploaded video is empty.", kind="unsupported_format") from exc
    if size_bytes <= 0:
        raise MouthMapHFError("Uploaded video is empty.", kind="unsupported_format")
    timeout = max(30, int(settings.MOUTHMAP_HF_TIMEOUT_S or 180))
    upload_timeout = max(15, int(settings.MOUTHMAP_UPLOAD_TIMEOUT_S or 60))
    started = time.monotonic()
    logger.info(
        "mouthmap inference requested file=%s bytes=%d", filename, size_bytes
    )

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        # 1. Upload (streams from disk; short dedicated timeout so a slow
        # upload cannot burn the whole inference budget).
        try:
            with open(video_path, "rb") as fh:
                files = {"files": (filename, fh, content_type)}
                resp = await client.post(
                    f"{base}/gradio_api/upload",
                    files=files,
                    headers=_auth_headers(),
                    timeout=httpx.Timeout(upload_timeout),
                )
        except httpx.TimeoutException as exc:
            raise MouthMapHFError(
                "Inference timed out while uploading video", kind="timeout"
            ) from exc
        except httpx.HTTPError as exc:
            raise MouthMapHFError(
                "MouthMap inference service is currently unavailable",
                kind="unavailable",
            ) from exc
        if resp.status_code == 413:
            raise MouthMapHFError("Video is too large", kind="unsupported_format")
        if resp.status_code >= 400:
            raise MouthMapHFError(
                "MouthMap inference service is currently unavailable",
                kind="unavailable",
            )
        try:
            paths = resp.json()
        except ValueError as exc:
            raise MouthMapHFError(
                "Unexpected upload response from inference service", kind="malformed"
            ) from exc
        if not paths or not isinstance(paths, list):
            raise MouthMapHFError(
                "Unexpected upload response from inference service", kind="malformed"
            )
        server_path = str(paths[0])

        # 2. Enqueue prediction (retry once on 502/503)
        accepted = False
        payload = {"video": {"path": server_path, "meta": dict(_FILEDATA_META)}}
        event_id: str | None = None
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                resp = await client.post(
                    f"{base}/gradio_api/call/v2/predict",
                    json=payload,
                    headers=_auth_headers(),
                )
                if resp.status_code in (502, 503) and attempt == 0:
                    await asyncio.sleep(2)
                    continue
                resp.raise_for_status()
                event_id = str(resp.json().get("event_id"))
                break
            except httpx.TimeoutException as exc:
                last_err = exc
                break
            except httpx.HTTPError as exc:
                last_err = exc
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                break
        if not event_id or event_id in ("None", ""):
            if isinstance(last_err, httpx.TimeoutException):
                raise MouthMapHFError(
                    "Inference timed out. Please try again.", kind="timeout"
                ) from last_err
            raise MouthMapHFError(
                "MouthMap inference service is currently unavailable",
                kind="unavailable",
            ) from last_err

        # The Space has accepted the run: from here a failure must never be
        # retried by the caller (the inference may already be executing).
        accepted = True

        # 3. Poll SSE until complete
        deadline = time.monotonic() + timeout
        raw: dict | None = None
        while time.monotonic() < deadline:
            try:
                resp = await client.get(
                    f"{base}/gradio_api/call/predict/{event_id}",
                    headers={"Accept": "text/event-stream", **_auth_headers()},
                )
                body = resp.text
            except httpx.TimeoutException:
                continue
            except httpx.HTTPError as exc:
                raise MouthMapHFError(
                    "MouthMap inference service is currently unavailable",
                    kind="unavailable",
                    accepted=accepted,
                ) from exc
            if "event: complete" in body:
                try:
                    raw = _parse_sse_payload(body)
                except MouthMapHFError as exc:
                    # The Space already ran the inference — never retry it.
                    exc.accepted = True
                    raise
                break
            if "event: error" in body:
                raise MouthMapHFError(
                    "MouthMap inference failed", kind="unavailable", accepted=accepted
                )
            await asyncio.sleep(1.5)
        if raw is None:
            raise MouthMapHFError(
                "Inference timed out. Please try again.", kind="timeout", accepted=accepted
            )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info("mouthmap inference completed in %dms file=%s", elapsed_ms, filename)
    normalized = normalize_hf_result(raw)
    if normalized.get("inference_time_ms") is None:
        normalized["inference_time_ms"] = elapsed_ms
    return normalized, raw


# ---------------------------------------------------------------------------
# Readiness / wake-up
#
# Verified against the live Space (kavinraja/mouthmap-inference, Gradio 6.x):
#   * the Space is PRIVATE — an unauthenticated request returns 404, so the
#     server-side MOUTHMAP_HF_API_TOKEN is sent as Bearer on every probe;
#   * GET {base}/config returns 200 with Gradio's config JSON (default
#     "api_prefix": "/gradio_api") ONLY once the uvicorn/Gradio process is
#     fully serving. While the Space is asleep/booting the request times out,
#     errors, returns a non-200, or returns a non-JSON interstitial page.
# So `/config` + JSON is the readiness signal: the request itself also
# triggers Hugging Face's factory wake, and we poll until bounded by
# MOUTHMAP_WAKE_TIMEOUT_S.
# ---------------------------------------------------------------------------

_ready_until: float = 0.0
_wake_lock: asyncio.Lock | None = None


def _wake_guard() -> asyncio.Lock:
    """Lazily-created process-wide lock so concurrent callers share one wake."""
    global _wake_lock
    if _wake_lock is None:
        _wake_lock = asyncio.Lock()
    return _wake_lock


def invalidate_ready_cache() -> None:
    """Drop a cached 'ready' verdict so the next check re-probes the Space."""
    global _ready_until
    _ready_until = 0.0


async def _probe_ready(timeout_s: float) -> bool:
    """One bounded readiness probe. Never raises on transport/protocol issues."""
    base = _base_url()
    if not base:
        return False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await client.get(f"{base}/config", headers=_auth_headers())
    except httpx.HTTPError:
        return False
    if resp.status_code != 200:
        return False
    try:
        cfg = resp.json()
    except ValueError:
        # A non-JSON body (e.g. the HF 'sleeping/restarting' page) is not ready.
        return False
    return isinstance(cfg, dict) and bool(cfg.get("api_prefix"))


async def ensure_hf_ready() -> None:
    """Ensure the Space is awake and serving before an inference run.

    Returns immediately when a recent probe confirmed readiness (short-lived
    cache). Otherwise probes and waits, bounded by MOUTHMAP_WAKE_TIMEOUT_S,
    for the Gradio app to serve ``/config``. Single-flight: concurrent callers
    share ONE wake cycle. Cancellation while waiting releases the lock and
    leaves the cache untouched.
    """
    base = _base_url()
    if not base:
        raise MouthMapHFError("MouthMap endpoint is not configured", kind="unavailable")

    global _ready_until
    if time.monotonic() < _ready_until:
        return

    total = max(1, int(settings.MOUTHMAP_WAKE_TIMEOUT_S or 180))
    interval = float(settings.MOUTHMAP_WAKE_POLL_INTERVAL_S or 4.0)
    interval = min(max(interval, 0.5), 30.0)
    probe_timeout = min(max(interval * 2.0, 5.0), 15.0)

    async with _wake_guard():
        # Another caller may have finished the wake while we waited for the lock.
        if time.monotonic() < _ready_until:
            return
        deadline = time.monotonic() + total
        while True:
            if await _probe_ready(probe_timeout):
                _ready_until = time.monotonic() + max(
                    1, int(settings.MOUTHMAP_READY_TTL_S or 600)
                )
                logger.info("mouthmap space ready")
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MouthMapHFError(
                    f"MouthMap model did not finish waking up within {total}s.",
                    kind="waking_timeout",
                )
            await asyncio.sleep(min(interval, remaining))


async def check_hf_health() -> tuple[bool, str | None]:
    """Lightweight health probe with a short timeout (no aggressive polling)."""
    base = _base_url()
    if not base:
        return False, "MouthMap endpoint is not configured"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
            resp = await client.get(f"{base}/config", headers=_auth_headers())
            if resp.status_code == 200:
                return True, None
            return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, type(exc).__name__
