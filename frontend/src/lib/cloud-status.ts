/** Per-surface kLLM Cloud status helpers.
 *
 * Chat and Reviews are independent gates on the backend: a model approved
 * for one surface is not implied for the other, and readiness can differ
 * (a model may be ready for Chat but not enabled for Reviews). The status
 * page therefore renders one state per surface instead of a single pill.
 */

import type { CloudModelStatus } from './api';

export type CloudSurface = 'chat' | 'review';

/** Wording mirrors the backend reason codes and the chat picker. */
export const CLOUD_REASON_TEXT: Record<string, string> = {
  ready: 'Ready',
  not_approved: 'Awaiting administrator approval',
  chat_not_enabled: 'Chat is not enabled for this model',
  review_not_enabled: 'Reviews are not enabled for this model',
  model_disabled: 'Temporarily disabled',
  model_removed: 'No longer offered by kLLM Cloud',
  kllm_cloud_disabled: 'kLLM Cloud is unavailable',
  kllm_cloud_unreachable: 'kLLM Cloud is unreachable',
  kllm_cloud_catalog_stale: 'The catalogue is stale',
  kllm_cloud_not_configured: 'kLLM Cloud is not configured',
};

export function cloudReasonText(code: string | null | undefined): string {
  if (!code) return 'Unavailable';
  return CLOUD_REASON_TEXT[code] ?? 'Unavailable';
}

export interface CloudSurfaceState {
  surface: CloudSurface;
  label: string;
  /** Administrator enabled this surface for the model. */
  enabled: boolean;
  /** The surface is enabled *and* the backend reports it ready now. */
  ready: boolean;
  reasonCode: string;
  reasonText: string;
  tone: 'success' | 'warning' | 'muted';
}

function state(
  surface: CloudSurface,
  label: string,
  enabled: boolean,
  ready: boolean,
  reasonCode: string | undefined,
): CloudSurfaceState {
  const code = reasonCode || (ready ? 'ready' : enabled ? 'unknown' : `${surface}_not_enabled`);
  const reasonText = ready ? 'Ready' : cloudReasonText(code);
  return {
    surface,
    label,
    enabled,
    ready,
    reasonCode: code,
    reasonText,
    tone: ready ? 'success' : enabled ? 'warning' : 'muted',
  };
}

/**
 * One entry per surface, in display order. Never derives one surface from
 * another: Chat falls back to the legacy `ready` alias only because the
 * backend documents that alias as Chat, while Review has no alias at all.
 */
export function surfaceStates(model: CloudModelStatus): CloudSurfaceState[] {
  const chatReady = model.chat_ready ?? model.ready === true;
  const chatReason = model.chat_reason_code ?? model.reason_code;
  return [
    state('chat', 'Chat', model.chat_enabled === true, chatReady, chatReason),
    state('review', 'Reviews', model.review_enabled === true, model.review_ready === true, model.review_reason_code),
  ];
}

export function surfaceLabel(item: CloudSurfaceState): string {
  if (item.ready) return `${item.label}: Ready`;
  if (!item.enabled) return `${item.label}: off`;
  return `${item.label}: ${item.reasonText}`;
}
