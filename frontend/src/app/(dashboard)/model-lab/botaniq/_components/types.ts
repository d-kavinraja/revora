'use client';

import type {
  BotaniQConfig,
  BotaniQHistoryItem,
  BotaniQInferenceResult,
  BotaniQSampleImage,
} from '@/lib/api';

export type Phase =
  | 'idle'
  | 'warming'
  | 'uploading'
  | 'processing'
  | 'completed'
  | 'failed';
export type InputTab = 'upload' | 'url' | 'dataset';

export interface SelectedImage {
  kind: 'upload' | 'url' | 'dataset';
  filename: string;
  blob?: Blob;
  objectUrl: string;
  sizeBytes?: number | null;
  testImageId?: string;
  label?: string | null;
}

export type { BotaniQConfig, BotaniQHistoryItem, BotaniQInferenceResult, BotaniQSampleImage };

export function fmtBytes(n?: number | null) {
  if (n == null) return 'N/A';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function friendlyError(err: unknown): string {
  const e = err as { code?: string; message?: string; response?: { status?: number; data?: { detail?: unknown } } };
  const code = typeof e?.code === 'string' ? e.code : '';
  const status = typeof e?.response?.status === 'number' ? e.response.status : null;
  if (code === 'ERR_NETWORK') return 'Cannot reach the backend server. Check that the API is running.';
  if (code === 'ECONNABORTED') return 'Inference request timed out. Please try again.';
  if (status === 401) return 'Your session has expired. Please sign in again.';
  if (status === 429) return 'Too many requests. Please wait a moment and try again.';
  const rawDetail = e?.response?.data?.detail;
  const detail = Array.isArray(rawDetail)
    ? rawDetail.map((d) => (typeof d === 'object' && d !== null ? String((d as { msg?: unknown }).msg ?? '') : String(d))).filter(Boolean).join(' ')
    : ((rawDetail as string | undefined) ?? (err as Error)?.message ?? '');
  if (/too large|maximum size/i.test(detail)) return detail;
  if (/timed out|timeout|504/i.test(detail)) return 'Inference timed out. Please try again.';
  if (/waking up|did not finish waking/i.test(detail)) return detail;
  if (/unavailable|502|503/i.test(detail)) return 'BotaniQ inference service is currently unavailable. Please try again later.';
  if (/could not fetch|publicly accessible/i.test(detail)) return detail;
  if (/not supported|unsupported/i.test(detail)) return detail;
  return detail || 'Something went wrong. Please try again.';
}
