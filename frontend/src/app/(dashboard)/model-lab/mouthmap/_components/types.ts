'use client';

import type {
  MouthMapHistoryItem,
  MouthMapInferenceResult,
} from '@/lib/api';

export type Phase =
  | 'idle'
  | 'warming'
  | 'uploading'
  | 'preparing'
  | 'processing'
  | 'completed'
  | 'failed';
export type SourceTab = 'dataset' | 'upload' | 'record';
export type UploadMode = 'upload' | 'record';

export interface SelectedVideo {
  kind: 'dataset' | 'upload' | 'record';
  filename: string;
  blob?: Blob;
  objectUrl: string;
  sizeBytes?: number | null;
  durationS?: number | null;
  resolution?: string | null;
  testVideoId?: string;
  expected?: string | null;
}

export interface RerunnableHistory extends MouthMapHistoryItem {
  test_video_id: string | null;
}

export type { MouthMapInferenceResult };

export function fmtBytes(n?: number | null) {
  if (n === null || n === undefined) return 'N/A';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function fmtDuration(s?: number | null) {
  if (s === null || s === undefined || Number.isNaN(s)) return 'N/A';
  return `${s.toFixed(1)}s`;
}

export function fmtClock(s?: number | null) {
  if (s === null || s === undefined || Number.isNaN(s) || !Number.isFinite(s)) return '—';
  const total = Math.max(0, Math.floor(s));
  const mm = String(Math.floor(total / 60)).padStart(2, '0');
  const ss = String(total % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

/**
 * True MouthMap preprocessing geometry (fixed crop, NOT a detector).
 * Source: hf-space/app.py load_video — frame[190:236, 80:220],
 * 75 linspace-sampled frames, grayscale, 46x140 model input.
 */
export const MODEL_INPUT = {
  x: 80,
  y: 190,
  w: 140,
  h: 46,
  frames: 75,
} as const;

export function metric(v: string | number | null | undefined) {
  if (v === null || v === undefined || v === '') return 'N/A';
  return String(v);
}

/** Schemes a media element is ever allowed to load in Model Lab. `blob:`
 *  covers every legitimate source (upload, recording, and dataset bytes
 *  all reach the UI as URL.createObjectURL results); `https:` covers
 *  backend-served media. `http:` is deliberately excluded — no code path
 *  needs it, so an explicit change here is required before one ever can.
 *  Everything else (javascript:, data:, vbscript:, file:, …) is rejected.
 */
const SAFE_MEDIA_SCHEMES: ReadonlySet<string> = new Set(['blob:', 'https:']);

/**
 * Trust boundary for media element sources (CodeQL js/xss-through-dom).
 * Only browser-generated blob URLs and https URLs may reach a
 * <video>/<audio> `src`. Anything else — non-strings, empty values,
 * whitespace/control-character tricks, schemeless or malformed URLs, and
 * non-allowlisted schemes — is rejected so callers fail closed into
 * their existing error UI instead of handing the string to the DOM.
 */
export function isSafeMediaUrl(url: unknown): url is string {
  if (typeof url !== 'string') return false;
  const v = url.trim();
  if (!v) return false;
  // Raw spaces, quotes, angle brackets, backticks, and backslashes are
  // never valid unencoded in a URL: reject before parsing so parser
  // leniency (e.g. stripped newlines) cannot smuggle a scheme through.
  if (/[\s<>"'`\\]/.test(v)) return false;
  let parsed: URL;
  try {
    // Relative URLs throw without a base (correct: no relative media
    // source exists in this app); opaque blob: URLs parse normally.
    parsed = new URL(v);
  } catch {
    return false;
  }
  const scheme = parsed.protocol.toLowerCase();
  if (!SAFE_MEDIA_SCHEMES.has(scheme)) return false;
  // A bare `blob:` (empty path) can never come from createObjectURL and
  // loads nothing: require a fully-formed URL so only real media passes.
  if (scheme === 'blob:' && !parsed.pathname) return false;
  return true;
}

export function friendlyError(err: unknown): string {
  const axiosErr = err as {
    code?: unknown;
    message?: unknown;
    response?: { status?: unknown; data?: { detail?: unknown } };
  };
  const code =
    typeof axiosErr?.code === 'string' ? axiosErr.code : '';
  const status =
    typeof axiosErr?.response?.status === 'number'
      ? axiosErr.response.status
      : null;

  // Transport-level failures: no HTTP response was received (backend
  // down/restarting, wrong port, or CORS-blocked origin). These carry
  // no `detail`, so translate the axios code into an actionable hint.
  if (code === 'ERR_NETWORK')
    return 'Cannot reach the backend server (network error). Check that the API is running and that this page\u2019s origin is allowed by the backend CORS settings.';
  if (code === 'ECONNABORTED')
    return 'Inference request timed out. Please try again.';
  if (status === 401)
    return 'Your session has expired. Please sign in again.';
  if (status === 429)
    return 'Too many requests. Please wait a moment and try again.';

  const rawDetail = axiosErr?.response?.data?.detail;
  // FastAPI validation errors carry `detail` as an array of objects —
  // never return it verbatim (React cannot render objects).
  const detail = Array.isArray(rawDetail)
    ? rawDetail
        .map((d) =>
          typeof d === 'string'
            ? d
            : typeof d === 'object' && d !== null
              ? String((d as { msg?: unknown }).msg ?? '')
              : '',
        )
        .filter(Boolean)
        .slice(0, 2)
        .join(' ')
    : ((rawDetail as string | undefined) ?? (err as Error)?.message ?? '');
  if (/not supported/i.test(detail))
    return 'Video format is not supported. Use MP4, WebM, or MPG.';
  if (/too large|maximum size/i.test(detail)) return detail;
  if (/timed out|timeout|504/i.test(detail))
    return 'Inference timed out. Please try again.';
  // Wake-up window elapsed: the backend's actionable message is clearer than
  // the generic "unavailable" copy, so surface it verbatim.
  if (/waking up|did not finish waking/i.test(detail)) return detail;
  if (/unavailable|502|503/i.test(detail))
    return 'MouthMap inference service is currently unavailable. Please try again later.';
  return detail || 'Something went wrong. Please try again.';
}
