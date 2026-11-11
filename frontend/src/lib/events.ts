'use client';

import { useEffect, useRef } from 'react';
import { API_BASE } from '@/lib/api';
import { useAuthStore } from '@/store/useAuthStore';

export type ReviewStreamEvent = {
  type: 'review.updated' | 'pr.state' | 'heartbeat';
  review_id?: string;
  pr_id?: string;
  status?: string;
  error_message?: string | null;
  pr_number?: number;
  repo_id?: string;
  updated_at?: string;
};

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  );
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

/**
 * Subscribes to an SSE stream via fetch (EventSource cannot send the
 * Authorization header). Auto-reconnects with backoff on drops so the
 * 30s polling fallback never has to carry the UI alone.
 *
 * The connection is aborted on unmount. Without this, React Strict Mode and
 * client-side navigation leave the old fetch/body stream alive; when the
 * browser tears it down the reader can reject with a non-Error event (logged
 * by Next as an opaque `[object ErrorEvent]`). The abort is the intended
 * lifecycle, so it is handled locally and never reconnects after cleanup.
 */
export function useReviewStream(
  url: string,
  onEvent: (event: ReviewStreamEvent) => void,
): void {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!isAuthenticated) return;

    const controller = new AbortController();
    let active = true;
    let retryMs = 2000;
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

    const connect = async () => {
      while (active && !controller.signal.aborted) {
        try {
          // Cookie-based auth: the HttpOnly session cookie rides along;
          // send the in-memory Bearer too when present (same tab).
          const token = useAuthStore.getState().token;
          const res = await fetch(url, {
            credentials: 'include',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            signal: controller.signal,
          });
          if (!res.ok || !res.body) throw new Error(`SSE ${res.status}`);
          reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          retryMs = 2000;
          while (active && !controller.signal.aborted) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let sep = buffer.indexOf('\n\n');
            while (sep !== -1) {
              const chunk = buffer.slice(0, sep);
              buffer = buffer.slice(sep + 2);
              const line = chunk.split('\n').find((l) => l.startsWith('data: '));
              if (line) {
                try {
                  onEventRef.current(JSON.parse(line.slice(6)));
                } catch (error) {
                  // Malformed frames are recoverable; callback failures are
                  // app bugs and must stay visible.
                  console.error('[reviews] failed to handle SSE frame', {
                    url,
                    error,
                  });
                }
              }
              sep = buffer.indexOf('\n\n');
            }
          }
        } catch (error) {
          if (!active || controller.signal.aborted || isAbortError(error)) {
            return;
          }
          console.warn('[reviews] SSE stream disconnected; retrying', {
            url,
            retryMs,
            error:
              error instanceof Error
                ? { name: error.name, message: error.message, stack: error.stack }
                : error,
          });
        } finally {
          if (reader) {
            try {
              await reader.cancel();
            } catch {
              // The stream may already be closed by navigation.
            }
            reader = null;
          }
        }

        if (active && !controller.signal.aborted) {
          await sleep(retryMs, controller.signal);
          retryMs = Math.min(retryMs * 2, 15000);
        }
      }
    };

    void connect().catch((error) => {
      if (!controller.signal.aborted) {
        console.error('[reviews] SSE connection loop crashed', { url, error });
      }
    });

    return () => {
      active = false;
      controller.abort();
      if (reader) {
        void reader.cancel().catch(() => {});
        reader = null;
      }
    };
  }, [url, isAuthenticated]);
}

/** URL of the global reviews stream. */
export function reviewsStreamUrl(): string {
  return `${API_BASE}/reviews/stream`;
}

/** URL of the per-review stream. */
export function reviewStreamUrl(reviewId: string): string {
  return `${API_BASE}/reviews/${reviewId}/stream`;
}
