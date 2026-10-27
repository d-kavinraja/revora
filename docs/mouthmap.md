# MouthMap Model Lab

Inference-only lip-reading workspace at `/model-lab` (Beta).
Revora forwards video to the hosted Hugging Face Gradio Space and renders the result.
No training code, no TensorFlow, and no model weights exist in Revora.

## UI layout (reference-aligned)

Breadcrumb → gradient hero → 3-column workspace
(Upload | Test Dataset | Model Configuration) → Video Analysis & Results
→ dense Test History table.

Video Analysis & Results uses two separate grids:
Row 1 (`grid-cols-1 lg:grid-cols-2`) — Original Video | Model Input Region;
Row 2 (`grid-cols-1 lg:grid-cols-3`) — Inference Result | Inference Metrics
| Inference Output (JSON). Result and Metrics cards appear only after the
first inference; until then the JSON card spans the full row. Record lives
inside the Upload card (Upload | Record toggle). Configuration is info-only;
every metric without data renders `N/A` (Model shows `MouthMap`).

## Model input visualization (Option B)

The pipeline has no face/mouth detector — localization is the fixed
preprocessing crop `frame[190:236, 80:220]` (46x140, 75 frames,
grayscale). The Analysis workspace draws this TRUE crop over the
actual selected frame on a canvas, plus the same region rendered in
grayscale beside it, labeled "Model Input Region — fixed
preprocessing crop, not detected landmarks". Purely client-side;
no backend, HF, or model changes.

## Upload contract (browser → FastAPI)

`mouthmapApi.runInference` sends `FormData(video, test_video_id?, source)`
with **no manual `Content-Type` header** — the browser generates the
multipart boundary automatically (a hardcoded `multipart/form-data`
header without boundary makes FastAPI reject the request at form
parsing, before the endpoint runs). Dataset rows derive their status
pill from the live request phase, so a failed inference shows Failed,
never stuck Running.

## Architecture

Browser → Next.js `/model-lab` → FastAPI `/api/v1/mouthmap/*` → HF Space → normalized response → UI + Postgres history.

The React app never calls Hugging Face directly and never sees any HF token.

## Hugging Face contract (verified live)

Space: `https://huggingface.co/spaces/kavinraja/mouthmap-inference`
Base: `https://kavinraja-mouthmap-inference.hf.space`

1. `POST {base}/gradio_api/upload` — multipart field `files` → `["/tmp/gradio/.../name.mp4"]`
2. `POST {base}/gradio_api/call/v2/predict` — body
   `{"video": {"path": "<uploaded_path>", "meta": {"_type": "gradio.FileData"}}}` → `{"event_id": "..."}`
3. `GET {base}/gradio_api/call/predict/{event_id}` (SSE) → `event: complete` with `data: [{prediction, ...}]`

The Space is public (no token required). `MOUTHMAP_HF_API_TOKEN` is supported server-side only for private deployments.

## Inference compatibility (owned by the HF service)

75 frames · 46×140 fixed crop `frame[190:236, 80:220]` · mean/std normalize
· input `(1,75,46,140,1)` · Conv3D→Pool ×3 → Reshape → BiLSTM→Dropout ×2
→ Dense softmax · greedy CTC decode (`input_length=[75]`) ·
vocab `a-z0-9'?! ` · `!`→space cleanup · `.align` sil-strip on both ends.

Grayscale + normalization are **verbatim the original Streamlit
pipeline**: `tf.image.rgb_to_grayscale` applied to the cv2 BGR frame
(weights `[0.2989, 0.5870, 0.1140]` on stored channel order — NOT
`cv2.COLOR_BGR2GRAY`, which swaps the R/B weights and measurably
changes predictions), then `mean = tf.math.reduce_mean(frames)` /
`std = tf.math.reduce_std(tf.cast(frames, tf.float32))` /
`tf.cast(frames - mean, tf.float32) / std`. The ONLY intentional
addition is an `std = max(std, 1e-6)` guard against division by zero
on degenerate constant videos; real videos have std ~30-60 and are
unaffected. The Model Input Region visualization uses the same
effective luma, so UI and model agree.

## Environment

```env
MOUTHMAP_HF_ENDPOINT_URL=https://kavinraja-mouthmap-inference.hf.space
# MOUTHMAP_HF_API_TOKEN=   # server-side only, never NEXT_PUBLIC_
MOUTHMAP_MAX_UPLOAD_MB=50
MOUTHMAP_MODEL_VERSION=mouthmap-v1
MOUTHMAP_WAKE_TIMEOUT_S=180
MOUTHMAP_WAKE_POLL_INTERVAL_S=4
MOUTHMAP_READY_TTL_S=600
```

The Space is **private**: an unauthenticated request returns `404`, so
`MOUTHMAP_HF_API_TOKEN` (server-side, Bearer) is required for every call.

## Test dataset

Real videos live in `backend/app/mouthmap/dataset/`:

```text
<stem>.mp4|.webm|.mpg
<stem>.align            # optional GRID-style alignment, matched by stem
manifest.json          # optional [{id, filename, ground_truth, duration_s, resolution}]
```

An empty directory is valid — the API returns `[]` and the UI shows an empty state. Never commit placeholder media.

Seeded real data: `bbaf2n.mp4` (90 frames, 360x288, ~3s) + `bbaf2n.align`
→ ground truth `bin blue at f two now`.
End-to-end proof via `gradio_client` on 2026-10-08: `status: completed`,
prediction `et ge th tere son` (honest mismatch on this sample).

## Space file-handling fix

`hf-space/` mirrors the Space source with the API-layer fix (model code untouched):
`resolve_video_path()` (str / FileData-dict / `.path`-object),
`validate_video_file()` before inference (exists, size, `isOpened`, one readable frame),
server path used directly (no temp copy, no `.mp4` fallback),
`gradio==6.29.1` pinned. Apply to the Space, then verify UI → client → Revora.

## Failure semantics

| Cause | Revora status |
|---|---|
| Unsupported extension / oversize / empty | 422 / 413 with actionable message |
| Space rejects content (invalid/incomplete video) | 422 with the Space message |
| Space down / HTTP error | 502 generic |
| Space/queue timeout | 504, retry suggested |
| Space not ready within wake window | 503, "did not finish waking up" + Retry |

## Metrics and error diagnostics

`inference_time_ms` is the Space's measured model inference time
(`raw["timing"]["inference_ms"]`); legacy flat timing keys are kept for
back-compat, and the client round-trip time is only the final fallback.
The model metric shows `MouthMap`; confidence is `N/A` unless the
service ever returns one (no fabrication).

Frontend `friendlyError()` translates transport failures into
actionable text: `ERR_NETWORK` → backend unreachable / CORS hint,
`ECONNABORTED` → timeout, 401 → re-sign-in, 429 → back off. Business
logic is unchanged; CORS origins are not widened.

## API

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v1/mouthmap/config` | JWT | limits, formats, model info |
| GET | `/api/v1/mouthmap/health` | JWT | short-timeout HF probe |
| POST | `/api/v1/mouthmap/warm` | JWT | wake the Space, bounded by `MOUTHMAP_WAKE_TIMEOUT_S` |
| GET | `/api/v1/mouthmap/dataset` | JWT | real entries only |
| GET | `/api/v1/mouthmap/dataset/{id}/stream` | JWT | preview via authed fetch→blob |
| POST | `/api/v1/mouthmap/inference` | JWT | multipart `video` + `test_video_id?` + `source?` |
| GET | `/api/v1/mouthmap/history` | JWT | owner-scoped, `?limit&offset` |

## Sleep recovery / wake-up

Hugging Face Spaces on the free tier pause after inactivity. Readiness is
detected server-side via `GET {base}/config` (200 + Gradio config JSON with
`api_prefix`); while the Space is asleep that request times out, returns a
non-200, or returns a non-JSON interstitial — all treated as "not ready".

- **On demand only:** the client calls `POST /mouthmap/warm` when the user
  starts a run. Page loads never wake the model. The inference endpoint also
  warms as a safety net (immediately, from the ready cache, when warm).
- **Single-flight:** concurrent callers share one wake cycle via a
  process-wide lock; a successful wake is cached for `MOUTHMAP_READY_TTL_S`.
- **Bounded:** if the Space does not become ready within
  `MOUTHMAP_WAKE_TIMEOUT_S`, the backend stops and returns `503` with a
  "did not finish waking up" message; the UI shows it with a manual Retry.
- **At-most-once retry:** a run is retried **once** after a re-warm, and only
  when it failed *before* the Space accepted it (no `event_id`). Post-
  acceptance failures are never retried, so a possibly-executing inference is
  never duplicated.

### Manual local test steps

```bash
# backend (restart after code changes so the new settings/routes load)
cd backend && .\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# frontend
cd frontend && npm run dev
```

1. **Waking / success:** open `/model-lab/mouthmap`, pick a test video, Run.
   A "Waking up model" stage appears while the backend confirms readiness,
   then Upload → Running inference → result. (If the Space is warm, the wake
   stage is brief.)
2. **Timeout:** set `MOUTHMAP_WAKE_TIMEOUT_S=10` (env) and restart the backend,
   then start a run against a sleeping Space. After ~10s the run fails with
   "MouthMap model did not finish waking up within 10s." and a Retry button.
3. **Recovery:** with the Space warm, confirm a normal run is unchanged
   (no visible wake delay, same result contract).

## Tests

```bash
cd backend
alembic upgrade head   # required once: creates mouthmap_inference_runs
python -m pytest tests/test_mouthmap.py -q   # 13 passed
python -m pytest tests/ -q                    # 405 passed
python -m ruff check app/mouthmap app/models/mouthmap.py tests/test_mouthmap.py
cd ../frontend
npx tsc --noEmit
npm run build   # /model-lab prerendered
```
