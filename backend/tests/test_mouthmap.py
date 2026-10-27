"""MouthMap backend tests (mocks only at the HF boundary, never in production)."""

import asyncio
import io
import os
import tempfile
import time

import pytest

from app.mouthmap import hf_client
from app.mouthmap.service import validate_video


@pytest.fixture(autouse=True)
def _stub_mouthmap_warm(monkeypatch):
    """Keep endpoint tests offline: never wake a real Space from the API path.

    The inference endpoint now warms the Space before running. Stub the
    service-level warm/invalidate hooks by default and reset the HF readiness
    cache between tests. Readiness tests exercise `hf_client.ensure_hf_ready`
    directly, which bypasses this stub.
    """
    import app.mouthmap.service as svc

    async def _noop_warm():
        return {"status": "ready"}

    monkeypatch.setattr(svc.mouthmap_service, "warm", _noop_warm, raising=False)
    monkeypatch.setattr(
        svc.mouthmap_service, "invalidate_ready", lambda: None, raising=False
    )
    monkeypatch.setattr(hf_client, "_ready_until", 0.0, raising=False)
    monkeypatch.setattr(hf_client, "_wake_lock", None, raising=False)
    yield


def _write_tmp_video(content: bytes = b"0" * 1024, suffix: str = ".mp4") -> str:
    fd, path = tempfile.mkstemp(prefix="mouthmap_test_", suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(content)
    return path


def test_validate_video_rejects_extension():
    with pytest.raises(Exception) as exc:
        validate_video("clip.avi", "video/avi", 100)
    assert "not supported" in str(exc.value).lower()


def test_validate_video_rejects_oversize(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "MOUTHMAP_MAX_UPLOAD_MB", 1)
    with pytest.raises(Exception) as exc:
        validate_video("clip.mp4", "video/mp4", 2 * 1024 * 1024)
    assert "too large" in str(exc.value).lower()


def test_normalize_hf_result_only_real_fields():
    norm = hf_client.normalize_hf_result(
        {"prediction": "hello world", "inference_time_ms": 1234}
    )
    assert norm["prediction"] == "hello world"
    assert norm["confidence"] is None
    assert norm["frames_processed"] is None
    assert norm["inference_time_ms"] == 1234


def test_normalize_hf_result_rejects_malformed():
    with pytest.raises(hf_client.MouthMapHFError):
        hf_client.normalize_hf_result({"unexpected": 1})


def test_normalize_hf_result_prefers_timing_inference_ms():
    norm = hf_client.normalize_hf_result(
        {
            "prediction": "bin blue at f two now",
            "model": "MouthMap",
            "model_version": "checkpoint.weights.h5",
            "frames_processed": 75,
            "timing": {
                "preprocessing_ms": 120.5,
                "inference_ms": 4321.7,
                "total_ms": 4500.2,
            },
        }
    )
    assert norm["prediction"] == "bin blue at f two now"
    assert norm["inference_time_ms"] == 4321
    assert norm["frames_processed"] == 75
    assert norm["confidence"] is None


def test_normalize_hf_result_legacy_flat_timing():
    norm = hf_client.normalize_hf_result(
        {"prediction": "hello", "inference_time": "900"}
    )
    assert norm["inference_time_ms"] == 900


def test_normalize_hf_result_timing_without_prediction_rejected():
    with pytest.raises(hf_client.MouthMapHFError):
        hf_client.normalize_hf_result(
            {"timing": {"inference_ms": 10}, "status": "completed"}
        )


def test_parse_sse_failed():
    with pytest.raises(hf_client.MouthMapHFError) as exc:
        hf_client._parse_sse_payload(
            'event: complete\ndata: [{"status": "failed", "error": "Unable to open video."}]\n\n'
        )
    assert exc.value.kind == "failed"
    assert "Unable to open video" in str(exc.value)


def test_parse_sse_success():
    raw = hf_client._parse_sse_payload(
        'event: info\ndata: ["partial"]\n\nevent: complete\ndata: [{"prediction": "hi"}]\n\n'
    )
    assert raw == {"prediction": "hi"}


async def _fake_run(video_path, filename, content_type):
    # Path-based contract: the staged file must exist on disk (never bytes).
    assert isinstance(video_path, str) and os.path.isfile(video_path)
    return (
        {
            "prediction": "hello",
            "model_version": "mouthmap-v1",
            "confidence": None,
            "inference_time_ms": 10,
            "frames_processed": None,
        },
        {"prediction": "hello"},
    )


def test_inference_requires_auth(client):
    from app.core.deps import get_current_user
    from app.main import app

    app.dependency_overrides.pop(get_current_user, None)
    try:
        resp = client.get("/api/v1/mouthmap/config")
        assert resp.status_code in (401, 403)
    finally:
        # restore override for other tests using the fixture pattern
        pass


def test_config_endpoint(client):
    resp = client.get("/api/v1/mouthmap/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "MouthMap"
    assert body["input_frames"] == 75
    assert ".mp4" in body["allowed_extensions"]


def test_dataset_lists_real_video_with_ground_truth(client):
    """Real dataset entry (bbaf2n.mp4 + bbaf2n.align) is served with parsed truth."""
    resp = client.get("/api/v1/mouthmap/dataset")
    assert resp.status_code == 200
    items = {v["id"]: v for v in resp.json()}
    assert "bbaf2n" in items
    entry = items["bbaf2n"]
    assert entry["filename"] == "bbaf2n.mp4"
    assert entry["size_bytes"] and entry["size_bytes"] > 0
    assert entry["has_alignment"] is True
    assert (entry["ground_truth"] or "").strip().lower() == "bin blue at f two now"


def test_inference_success_persists_history(client, monkeypatch):
    import app.mouthmap.service as svc

    monkeypatch.setattr(svc, "run_hf_inference", _fake_run)
    files = {"video": ("clip.mp4", io.BytesIO(b"0" * 1024), "video/mp4")}
    resp = client.post(
        "/api/v1/mouthmap/inference", files=files, data={"source": "upload"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["prediction"] == "hello"
    hist = client.get("/api/v1/mouthmap/history")
    assert hist.status_code == 200
    assert len(hist.json()) == 1
    assert hist.json()[0]["prediction"] == "hello"


def test_inference_unsupported_format(client):
    files = {"video": ("clip.avi", io.BytesIO(b"0" * 16), "video/avi")}
    resp = client.post("/api/v1/mouthmap/inference", files=files)
    assert resp.status_code == 422


async def _fake_run_failed(*args, **kwargs):
    raise hf_client.MouthMapHFError(
        "Uploaded video is invalid, incomplete, or unsupported.", kind="failed"
    )


def test_inference_space_rejection_surfaces_message(client, monkeypatch):
    import app.mouthmap.service as svc

    monkeypatch.setattr(svc, "run_hf_inference", _fake_run_failed)
    files = {"video": ("clip.mp4", io.BytesIO(b"0" * 1024), "video/mp4")}
    resp = client.post("/api/v1/mouthmap/inference", files=files)
    assert resp.status_code == 422
    assert "invalid" in resp.json()["detail"].lower()


def test_hf_token_never_exposed(client):
    resp = client.get("/api/v1/mouthmap/config")
    assert "token" not in resp.text.lower()


def test_hf_upload_streams_from_disk_not_memory(monkeypatch, tmp_path):
    """run_hf_inference must open the staged file, never take bytes."""
    import inspect

    sig = inspect.signature(hf_client.run_hf_inference)
    assert list(sig.parameters) == ["video_path", "filename", "content_type"]


def test_inference_busy_returns_429(client, monkeypatch):
    """A held inference slot must reject the next caller instantly."""
    import app.api.v1.endpoints.mouthmap as mm_ep

    async def hold_forever():
        await mm_ep._inference_slot().acquire()

    import asyncio

    asyncio.get_event_loop().run_until_complete(hold_forever())
    try:
        files = {"video": ("clip.mp4", io.BytesIO(b"0" * 1024), "video/mp4")}
        resp = client.post("/api/v1/mouthmap/inference", files=files)
        assert resp.status_code == 429
        assert "busy" in resp.json()["detail"].lower()
    finally:
        mm_ep._inference_slot().release()


def test_inference_oversize_rejected_without_full_buffer(client, monkeypatch):
    """Streaming cap rejects oversize uploads mid-stream (413)."""
    from app.core import config

    monkeypatch.setattr(config.settings, "MOUTHMAP_MAX_UPLOAD_MB", 1)
    files = {"video": ("clip.mp4", io.BytesIO(b"0" * (2 * 1024 * 1024)), "video/mp4")}
    resp = client.post("/api/v1/mouthmap/inference", files=files)
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"].lower()

    resp = client.get("/api/v1/mouthmap/health")
    assert "token" not in resp.text.lower()


async def test_missing_endpoint_raises_unavailable(monkeypatch):
    """No configured endpoint must fail safe without network or disk IO."""
    from app.core import config

    monkeypatch.setattr(config.settings, "MOUTHMAP_HF_ENDPOINT_URL", None)
    with pytest.raises(hf_client.MouthMapHFError) as exc:
        await hf_client.run_hf_inference(
            "/nonexistent/clip.mp4", "clip.mp4", "video/mp4"
        )
    assert exc.value.kind == "unavailable"
    assert "not configured" in str(exc.value).lower()


def test_health_empty_endpoint_when_unconfigured(client, monkeypatch):
    """Health stays schema-valid (endpoint == '') with no URL configured."""
    from app.core import config

    monkeypatch.setattr(config.settings, "MOUTHMAP_HF_ENDPOINT_URL", None)
    resp = client.get("/api/v1/mouthmap/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["endpoint"] == ""
    assert "not configured" in (body["detail"] or "").lower()
    assert "token" not in resp.text.lower()


# ---------------------------------------------------------------------------
# Readiness / wake-up (hf_client.ensure_hf_ready)
# ---------------------------------------------------------------------------


def _configure_wake(monkeypatch, *, timeout=5, interval=0.01, ttl=600):
    from app.core import config

    monkeypatch.setattr(
        config.settings, "MOUTHMAP_HF_ENDPOINT_URL", "https://space.test"
    )
    monkeypatch.setattr(config.settings, "MOUTHMAP_WAKE_TIMEOUT_S", timeout)
    monkeypatch.setattr(
        config.settings, "MOUTHMAP_WAKE_POLL_INTERVAL_S", interval
    )
    monkeypatch.setattr(config.settings, "MOUTHMAP_READY_TTL_S", ttl)


async def test_wakeup_succeeds_after_initial_probes_fail(monkeypatch):
    """Space asleep on the first probes, then ready — wake returns."""
    _configure_wake(monkeypatch)
    calls = []

    async def probe(timeout_s):
        calls.append(timeout_s)
        return len(calls) >= 3

    monkeypatch.setattr(hf_client, "_probe_ready", probe)
    await hf_client.ensure_hf_ready()
    assert len(calls) == 3
    assert hf_client._ready_until > time.monotonic()


async def test_wakeup_times_out_when_never_ready(monkeypatch):
    """A Space that never becomes ready raises waking_timeout and stays uncached."""
    _configure_wake(monkeypatch, timeout=1, interval=0.01)

    async def probe(timeout_s):
        return False

    monkeypatch.setattr(hf_client, "_probe_ready", probe)
    with pytest.raises(hf_client.MouthMapHFError) as exc:
        await hf_client.ensure_hf_ready()
    assert exc.value.kind == "waking_timeout"
    assert hf_client._ready_until == 0.0


async def test_wakeup_unconfigured_endpoint(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "MOUTHMAP_HF_ENDPOINT_URL", None)
    with pytest.raises(hf_client.MouthMapHFError) as exc:
        await hf_client.ensure_hf_ready()
    assert exc.value.kind == "unavailable"
    assert "not configured" in str(exc.value).lower()


async def test_wakeup_uses_ready_cache_without_probing(monkeypatch):
    _configure_wake(monkeypatch, timeout=0)
    monkeypatch.setattr(hf_client, "_ready_until", time.monotonic() + 100)
    calls = []

    async def probe(timeout_s):
        calls.append(1)
        return False

    monkeypatch.setattr(hf_client, "_probe_ready", probe)
    await hf_client.ensure_hf_ready()
    assert calls == []


async def test_wakeup_reprobes_after_cache_expiry(monkeypatch):
    _configure_wake(monkeypatch)
    calls = []

    async def probe(timeout_s):
        calls.append(1)
        return True

    monkeypatch.setattr(hf_client, "_probe_ready", probe)
    await hf_client.ensure_hf_ready()
    assert len(calls) == 1
    # Simulate the TTL elapsing: the next call must probe again.
    monkeypatch.setattr(hf_client, "_ready_until", time.monotonic() - 1)
    await hf_client.ensure_hf_ready()
    assert len(calls) == 2


async def test_wakeup_single_flight_shares_one_wake(monkeypatch):
    """Concurrent callers must share ONE wake cycle (one probe)."""
    _configure_wake(monkeypatch)
    calls = []

    async def probe(timeout_s):
        calls.append(1)
        await asyncio.sleep(0.05)  # hold so the second caller overlaps
        return True

    monkeypatch.setattr(hf_client, "_probe_ready", probe)
    await asyncio.gather(hf_client.ensure_hf_ready(), hf_client.ensure_hf_ready())
    assert len(calls) == 1
    assert hf_client._ready_until > time.monotonic()


async def test_wakeup_cancellation_releases_lock(monkeypatch):
    """A cancelled wake must release the single-flight lock and leave no cache."""
    _configure_wake(monkeypatch, timeout=30)
    entered = asyncio.Event()

    async def probe(timeout_s):
        entered.set()
        await asyncio.sleep(30)  # blocks until the task is cancelled
        return True

    monkeypatch.setattr(hf_client, "_probe_ready", probe)
    task = asyncio.create_task(hf_client.ensure_hf_ready())
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert hf_client._ready_until == 0.0
    # The lock must be free again.
    lock = hf_client._wake_guard()
    await asyncio.wait_for(lock.acquire(), timeout=1)
    lock.release()


# ---------------------------------------------------------------------------
# Warm endpoint
# ---------------------------------------------------------------------------


def test_warm_endpoint_returns_ready(client):
    """Already-awake path: warm resolves and returns the ready contract."""
    resp = client.post("/api/v1/mouthmap/warm")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ready"}


def test_warm_endpoint_requires_auth(client):
    from app.core.deps import get_current_user
    from app.main import app

    app.dependency_overrides.pop(get_current_user, None)
    resp = client.post("/api/v1/mouthmap/warm")
    assert resp.status_code in (401, 403)


def test_warm_endpoint_blocked_when_feature_disabled(client, monkeypatch):
    from app.services.platform_settings import platform_settings_service

    async def _disabled(key, db=None, *args, **kwargs):
        return {"status": "disabled", "message": None}

    monkeypatch.setattr(platform_settings_service, "get_flag", _disabled)
    resp = client.post("/api/v1/mouthmap/warm")
    assert resp.status_code == 503
    assert resp.json().get("code") == "feature_disabled"


# ---------------------------------------------------------------------------
# Inference recovery (at-most-once retry)
# ---------------------------------------------------------------------------


def test_inference_recovers_after_temporary_unavailability(client, monkeypatch):
    """A pre-acceptance failure re-warms and retries exactly once, then succeeds."""
    import app.mouthmap.service as svc

    calls = {"n": 0}

    async def flaky(video_path, filename, content_type):
        calls["n"] += 1
        if calls["n"] == 1:
            raise hf_client.MouthMapHFError(
                "MouthMap inference service is currently unavailable",
                kind="unavailable",
            )
        return (
            {
                "prediction": "hello",
                "model_version": "mouthmap-v1",
                "confidence": None,
                "inference_time_ms": 5,
                "frames_processed": None,
            },
            {"prediction": "hello"},
        )

    monkeypatch.setattr(svc, "run_hf_inference", flaky)
    files = {"video": ("clip.mp4", io.BytesIO(b"0" * 1024), "video/mp4")}
    resp = client.post(
        "/api/v1/mouthmap/inference", files=files, data={"source": "upload"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["prediction"] == "hello"
    assert calls["n"] == 2


def test_inference_does_not_retry_after_acceptance(client, monkeypatch):
    """A post-acceptance failure must NOT be retried (duplicate-run prevention)."""
    import app.mouthmap.service as svc

    calls = {"n": 0}

    async def accepted_fail(video_path, filename, content_type):
        calls["n"] += 1
        raise hf_client.MouthMapHFError(
            "Inference timed out. Please try again.", kind="timeout", accepted=True
        )

    monkeypatch.setattr(svc, "run_hf_inference", accepted_fail)
    files = {"video": ("clip.mp4", io.BytesIO(b"0" * 1024), "video/mp4")}
    resp = client.post("/api/v1/mouthmap/inference", files=files)
    assert resp.status_code == 504
    assert calls["n"] == 1


def test_inference_gives_up_after_single_recovery_attempt(client, monkeypatch):
    """Two pre-acceptance failures surface as an error (no infinite retry)."""
    import app.mouthmap.service as svc

    calls = {"n": 0}

    async def always_unavailable(video_path, filename, content_type):
        calls["n"] += 1
        raise hf_client.MouthMapHFError(
            "MouthMap inference service is currently unavailable", kind="unavailable"
        )

    monkeypatch.setattr(svc, "run_hf_inference", always_unavailable)
    files = {"video": ("clip.mp4", io.BytesIO(b"0" * 1024), "video/mp4")}
    resp = client.post("/api/v1/mouthmap/inference", files=files)
    assert resp.status_code == 502
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Error mapping (unchanged for existing kinds; new waking_timeout kind)
# ---------------------------------------------------------------------------


def test_error_accepted_flag_defaults_false():
    assert hf_client.MouthMapHFError("x").accepted is False
    assert hf_client.MouthMapHFError("x", accepted=True).accepted is True


def test_hf_error_to_http_mappings_unchanged():
    from app.api.v1.endpoints.mouthmap import _hf_error_to_http

    assert _hf_error_to_http(
        hf_client.MouthMapHFError("bad ext", kind="unsupported_format")
    ).status_code == 422
    assert _hf_error_to_http(
        hf_client.MouthMapHFError("Video is too large", kind="unsupported_format")
    ).status_code == 413
    assert _hf_error_to_http(
        hf_client.MouthMapHFError("space rejected", kind="failed")
    ).status_code == 422
    assert _hf_error_to_http(
        hf_client.MouthMapHFError("slow", kind="timeout")
    ).status_code == 504
    assert _hf_error_to_http(
        hf_client.MouthMapHFError("down", kind="unavailable")
    ).status_code == 502
    waking = _hf_error_to_http(
        hf_client.MouthMapHFError(
            "MouthMap model did not finish waking up within 180s.",
            kind="waking_timeout",
        )
    )
    assert waking.status_code == 503
    assert "waking up" in waking.detail.lower()
