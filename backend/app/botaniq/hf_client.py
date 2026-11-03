"""Hugging Face Gradio client for the BotaniQ medicinal plant classifier.

Verified Gradio contract (app_combined.py, api_name="predict_medicinal_plant"):
  1. POST {base}/gradio_api/upload  (multipart, field "files")  → [server_path]
  2. POST {base}/gradio_api/call/v2/predict_medicinal_plant
     {"image": {"path": server_path, "meta": {"_type": "gradio.FileData"}}}
     → {"event_id": "..."}
  3. GET  {base}/gradio_api/call/predict_medicinal_plant/{event_id}  (SSE)
     → "event: complete\ndata: [{...}]"

The Space is private.  MOUTHMAP_HF_API_TOKEN (server-side Bearer) is reused
since BotaniQ lives in the same Space as MouthMap.  The endpoint URL is
MOUTHMAP_HF_ENDPOINT_URL — no extra env var needed.

Response contract from app_combined.py predict_medicinal_plant():
  {
    "status": "completed" | "failed",
    "prediction": str,           # display name e.g. "Tulsi Leaf"
    "predicted_class": str,      # raw class key e.g. "leaf_Tulsi"
    "plant_name": str,
    "plant_type": "Leaf" | "Plant",
    "confidence": float,         # 0–100
    "model": str,
    "model_version": str,
    "classes_available": int,
    "top_5_predictions": [{"rank":int,"class":str,"confidence":float}, ...],
    "timing": {"preprocessing_ms":float,"inference_ms":float,"total_ms":float}
  }
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


class BotaniQHFError(Exception):
    def __init__(
        self, message: str, kind: str = "unavailable", *, accepted: bool = False
    ):
        super().__init__(message)
        # unsupported_format | timeout | unavailable | malformed | failed | waking_timeout
        self.kind = kind
        self.accepted = accepted


def _base_url() -> str:
    """BotaniQ shares the MouthMap Space — reuse the same base URL."""
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
    timing = result.get("timing")
    if isinstance(timing, dict):
        v = timing.get("inference_ms")
        if v is not None and v != "":
            return v
    return _pick_first(result, ["inference_time_ms", "inference_time", "elapsed_ms"])


def normalize_hf_result(result: dict) -> dict:
    """Normalize raw HF BotaniQ result into stable Revora contract.

    Never fabricates metrics — only populates fields that genuinely exist.
    """
    prediction = _pick_first(result, ["prediction", "predicted_class", "label", "class"])
    if prediction is None:
        raise BotaniQHFError(
            f"Unexpected inference response shape: {sorted(result.keys())}",
            kind="malformed",
        )

    # top_5_predictions: list of {"rank", "class", "confidence"}
    top5_raw = result.get("top_5_predictions")
    top5: list[dict] = []
    if isinstance(top5_raw, list):
        for item in top5_raw:
            if isinstance(item, dict):
                try:
                    top5.append(
                        {
                            "rank": int(item.get("rank", 0)),
                            "label": str(item.get("class", "")),
                            "confidence": round(float(item.get("confidence", 0.0)), 2),
                        }
                    )
                except (TypeError, ValueError):
                    pass

    out: dict = {
        "prediction": str(result.get("prediction") or prediction),
        "predicted_class": result.get("predicted_class"),
        "plant_name": result.get("plant_name"),
        "plant_type": result.get("plant_type"),
        "confidence": result.get("confidence"),
        "model_version": _pick_first(result, ["model_version", "version"]),
        "classes_available": result.get("classes_available"),
        "top_5_predictions": top5,
        "inference_time_ms": _pick_timing(result),
    }

    # Coerce numerics safely.
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
        out["classes_available"] = (
            int(out["classes_available"]) if out["classes_available"] is not None else None
        )
    except (TypeError, ValueError):
        out["classes_available"] = None

    return out


def _parse_sse_payload(body: str) -> dict:
    """Extract the final `data:` JSON array from the SSE stream."""
    data_lines = [
        line[5:].strip() for line in body.splitlines() if line.startswith("data:")
    ]
    if not data_lines:
        raise BotaniQHFError("Empty inference event stream", kind="malformed")
    try:
        payload = json.loads(data_lines[-1])
    except json.JSONDecodeError as exc:
        raise BotaniQHFError(
            "Malformed inference event stream", kind="malformed"
        ) from exc
    if not isinstance(payload, list) or not payload:
        raise BotaniQHFError("Unexpected inference payload shape", kind="malformed")
    first = payload[0]
    if isinstance(first, dict) and first.get("status") == "failed":
        raise BotaniQHFError(
            str(first.get("error") or "BotaniQ inference failed"), kind="failed"
        )
    if not isinstance(first, dict):
        raise BotaniQHFError("Unexpected inference payload shape", kind="malformed")
    return first


async def run_hf_inference(
    image_path: str, filename: str, content_type: str
) -> tuple[dict, dict]:
    """Upload image to HF Space and run predict_medicinal_plant. Returns (normalized, raw).

    The image streams from ``image_path`` on disk — never fully read into memory.
    """
    base = _base_url()
    if not base:
        raise BotaniQHFError("BotaniQ endpoint is not configured", kind="unavailable")
    try:
        size_bytes = os.path.getsize(image_path)
    except OSError as exc:
        raise BotaniQHFError(
            "Uploaded image is empty.", kind="unsupported_format"
        ) from exc
    if size_bytes <= 0:
        raise BotaniQHFError("Uploaded image is empty.", kind="unsupported_format")

    timeout = max(30, int(settings.BOTANIQ_HF_TIMEOUT_S or 120))
    upload_timeout = max(15, int(settings.BOTANIQ_UPLOAD_TIMEOUT_S or 60))
    started = time.monotonic()
    logger.info("botaniq inference requested file=%s bytes=%d", filename, size_bytes)

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        # 1. Upload — streams from disk
        try:
            with open(image_path, "rb") as fh:
                files = {"files": (filename, fh, content_type)}
                resp = await client.post(
                    f"{base}/gradio_api/upload",
                    files=files,
                    headers=_auth_headers(),
                    timeout=httpx.Timeout(upload_timeout),
                )
        except httpx.TimeoutException as exc:
            raise BotaniQHFError(
                "Inference timed out while uploading image", kind="timeout"
            ) from exc
        except httpx.HTTPError as exc:
            raise BotaniQHFError(
                "BotaniQ inference service is currently unavailable",
                kind="unavailable",
            ) from exc
        if resp.status_code == 413:
            raise BotaniQHFError("Image is too large", kind="unsupported_format")
        if resp.status_code >= 400:
            raise BotaniQHFError(
                "BotaniQ inference service is currently unavailable",
                kind="unavailable",
            )
        try:
            paths = resp.json()
        except ValueError as exc:
            raise BotaniQHFError(
                "Unexpected upload response from inference service", kind="malformed"
            ) from exc
        if not paths or not isinstance(paths, list):
            raise BotaniQHFError(
                "Unexpected upload response from inference service", kind="malformed"
            )
        server_path = str(paths[0])

        # 2. Enqueue prediction (api_name="predict_medicinal_plant")
        payload = {"image": {"path": server_path, "meta": dict(_FILEDATA_META)}}
        event_id: str | None = None
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                resp = await client.post(
                    f"{base}/gradio_api/call/v2/predict_medicinal_plant",
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
                raise BotaniQHFError(
                    "Inference timed out. Please try again.", kind="timeout"
                ) from last_err
            raise BotaniQHFError(
                "BotaniQ inference service is currently unavailable",
                kind="unavailable",
            ) from last_err

        accepted = True  # Space has taken ownership

        # 3. Poll SSE until complete
        deadline = time.monotonic() + timeout
        raw: dict | None = None
        while time.monotonic() < deadline:
            try:
                resp = await client.get(
                    f"{base}/gradio_api/call/predict_medicinal_plant/{event_id}",
                    headers={"Accept": "text/event-stream", **_auth_headers()},
                )
                body = resp.text
            except httpx.TimeoutException:
                continue
            except httpx.HTTPError as exc:
                raise BotaniQHFError(
                    "BotaniQ inference service is currently unavailable",
                    kind="unavailable",
                    accepted=accepted,
                ) from exc
            if "event: complete" in body:
                try:
                    raw = _parse_sse_payload(body)
                except BotaniQHFError as exc:
                    exc.accepted = True
                    raise
                break
            if "event: error" in body:
                raise BotaniQHFError(
                    "BotaniQ inference failed", kind="unavailable", accepted=accepted
                )
            await asyncio.sleep(1.5)
        if raw is None:
            raise BotaniQHFError(
                "Inference timed out. Please try again.", kind="timeout", accepted=accepted
            )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info("botaniq inference completed in %dms file=%s", elapsed_ms, filename)
    normalized = normalize_hf_result(raw)
    if normalized.get("inference_time_ms") is None:
        normalized["inference_time_ms"] = elapsed_ms
    return normalized, raw


# ---------------------------------------------------------------------------
# Readiness / wake-up  (reuses the same Space as MouthMap)
# ---------------------------------------------------------------------------

_ready_until: float = 0.0
_wake_lock: asyncio.Lock | None = None


def _wake_guard() -> asyncio.Lock:
    global _wake_lock
    if _wake_lock is None:
        _wake_lock = asyncio.Lock()
    return _wake_lock


def invalidate_ready_cache() -> None:
    global _ready_until
    _ready_until = 0.0


async def _probe_ready(timeout_s: float) -> bool:
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
        return False
    return isinstance(cfg, dict) and bool(cfg.get("api_prefix"))


async def ensure_hf_ready() -> None:
    """Ensure the shared Space is awake before a BotaniQ inference run."""
    base = _base_url()
    if not base:
        raise BotaniQHFError("BotaniQ endpoint is not configured", kind="unavailable")

    global _ready_until
    if time.monotonic() < _ready_until:
        return

    total = max(1, int(settings.BOTANIQ_WAKE_TIMEOUT_S or 180))
    interval = float(settings.BOTANIQ_WAKE_POLL_INTERVAL_S or 4.0)
    interval = min(max(interval, 0.5), 30.0)
    probe_timeout = min(max(interval * 2.0, 5.0), 15.0)

    async with _wake_guard():
        if time.monotonic() < _ready_until:
            return
        deadline = time.monotonic() + total
        while True:
            if await _probe_ready(probe_timeout):
                _ready_until = time.monotonic() + max(
                    1, int(settings.BOTANIQ_READY_TTL_S or 600)
                )
                logger.info("botaniq space ready")
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BotaniQHFError(
                    f"BotaniQ model did not finish waking up within {total}s.",
                    kind="waking_timeout",
                )
            await asyncio.sleep(min(interval, remaining))


async def check_hf_health() -> tuple[bool, str | None]:
    """Lightweight health probe (short timeout, no aggressive polling)."""
    base = _base_url()
    if not base:
        return False, "BotaniQ endpoint is not configured"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
            resp = await client.get(f"{base}/config", headers=_auth_headers())
            if resp.status_code == 200:
                return True, None
            return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, type(exc).__name__
