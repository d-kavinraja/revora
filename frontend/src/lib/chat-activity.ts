// Provider-neutral activity labels for the real signals available in Revora's
// chat stream. The SSE parser deliberately exposes no provider wait messages,
// free-form upstream status text, or private reasoning content.
import type { ResponsePhase } from './chat-state';

export type BackendStatusKind = 'thinking' | 'waking' | 'queued';

export interface ActivityContext {
  status?: BackendStatusKind | null;
  /** True only when validated prefill progress has arrived from the model. */
  hasPrefillProgress?: boolean;
  phase?: ResponsePhase | null;
  /** Seconds elapsed since this request was submitted. */
  elapsedSeconds?: number | null;
  /** Streamed answer text takes over the activity UI as soon as it arrives. */
  hasContent?: boolean;
}

export interface LiveChatActivity {
  assistantMessageId: string;
  startedAt: number;
  status: BackendStatusKind | null;
  hasPrefillProgress: boolean;
  hasContent: boolean;
}

export function elapsedActivitySeconds(activity: LiveChatActivity, now = Date.now()): number {
  return Math.max(0, Math.floor((now - activity.startedAt) / 1000));
}

export const SLOW_REQUEST_THRESHOLD_SECONDS = 30;

/** Generic periodic thinking ticks must not erase a known queue/warm-up state. */
export function mergeBackendStatus(
  previous: BackendStatusKind | null | undefined,
  next: BackendStatusKind,
  phase?: string | null,
): BackendStatusKind {
  // Backend heartbeat frames are explicitly marked as waiting for the first
  // token. Keep a known queue/warm-up state through those heartbeats, but let
  // a reasoning-status frame (which has no wait phase) advance to Thinking.
  if (
    (previous === 'waking' || previous === 'queued') &&
    next === 'thinking' &&
    phase === 'waiting_for_first_token'
  ) return previous;
  return next;
}

/** Map execution signals to concise copy without claiming unsupported work. */
export function activityLabelFor(input: ActivityContext): string | null {
  if (input.hasContent) return null;

  // Terminal events take precedence over the timer so a completed or failed
  // turn can never retain a stale "still working" label during cleanup.
  if (
    input.phase === 'complete' || input.phase === 'stopped' ||
    input.phase === 'error' || input.phase === 'truncated'
  ) return null;

  if (isSlow(input.elapsedSeconds)) {
    return 'Still working on your response…';
  }

  if (input.phase === 'generating') return 'Generating response…';
  // Validated progress means the model is actively processing the prompt, so
  // it supersedes earlier queue/warm-up status without inventing progress.
  if (input.hasPrefillProgress) return 'Reviewing context…';
  if (input.status === 'waking') return 'Warming up the model…';
  if (input.status === 'queued') return 'Preparing your response…';

  // A submitted request is real work even before the first backend event.
  // `preparing` is the shell's initial request phase, not a claim that the
  // model is running a distinct indexing or document-reading operation.
  if (
    input.phase === 'preparing' || input.phase === 'thinking' ||
    input.status === 'thinking' ||
    typeof input.elapsedSeconds === 'number'
  ) return 'Thinking…';

  return null;
}

function isSlow(elapsedSeconds: number | null | undefined): boolean {
  return typeof elapsedSeconds === 'number' && Number.isFinite(elapsedSeconds) &&
    elapsedSeconds >= SLOW_REQUEST_THRESHOLD_SECONDS;
}
