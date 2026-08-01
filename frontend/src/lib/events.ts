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

/**
 * Subscribes to an SSE stream via fetch (EventSource cannot send the
 * Authorization header). Auto-reconnects with backoff on drops so the
 * 30s polling fallback never has to carry the UI alone.
 */
export function useReviewStream(
  url: string,
  onEvent: (event: ReviewStreamEvent) => void,
): void {
  const token = useAuthStore((s) => s.token);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!token) return;
    let active = true;
    let retryMs = 2000;

    const connect = async () => {
      while (active) {
        try {
          const res = await fetch(url, {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (!res.ok || !res.body) throw new Error(`SSE ${res.status}`);
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          retryMs = 2000;
          while (active) {
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
                } catch {
                  // ignore malformed frames
                }
              }
              sep = buffer.indexOf('\n\n');
            }
          }
        } catch {
          // stream dropped — reconnect below
        }
        if (active) {
          await new Promise((r) => setTimeout(r, retryMs));
          retryMs = Math.min(retryMs * 2, 15000);
        }
      }
    };

    void connect();
    return () => {
      active = false;
    };
  }, [url, token]);
}

/** URL of the global reviews stream. */
export function reviewsStreamUrl(): string {
  return `${API_BASE}/reviews/stream`;
}

/** URL of the per-review stream. */
export function reviewStreamUrl(reviewId: string): string {
  return `${API_BASE}/reviews/${reviewId}/stream`;
}
