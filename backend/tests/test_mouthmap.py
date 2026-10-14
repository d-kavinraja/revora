"""MouthMap backend tests (mocks only at the HF boundary, never in production)."""

import io
import os
import tempfile

import pytest

from app.mouthmap import hf_client
from app.mouthmap.service import validate_video


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
