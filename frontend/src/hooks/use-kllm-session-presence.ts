'use client';

import { useEffect, useRef, useSyncExternalStore } from 'react';
import { api } from '@/lib/api';
import {
  endBrowserPresence,
  getBrowserSessionId,
  isPresenceActivityEvent,
  isRecentlyInteractive,
  KLLM_HEARTBEAT_INTERVAL_MS,
} from '@/lib/kllm-presence';
import { createPresenceHeartbeatQueue } from '@/lib/kllm-heartbeat-queue';
import { useAuthStore } from '@/store/useAuthStore';

let cachedSessionId: string | null = null;

function getSessionSnapshot(): string | null {
  if (typeof window === 'undefined') return null;
  if (!cachedSessionId) cachedSessionId = getBrowserSessionId();
  return cachedSessionId;
}

function subscribeToSession(): () => void {
  return () => undefined;
}

/** Browser-only tab id exposed as a stable external store (SSR-safe). */
export function useBrowserSessionId(): string | null {
  return useSyncExternalStore(subscribeToSession, getSessionSnapshot, () => null);
}

/**
 * Keeps this browser tab's advisory kLLM presence alive.
 *
 * Heartbeats are serialized by a "latest signal wins" queue. A deactivation
 * raised while an active heartbeat is in flight is sent immediately after that
 * request settles, so a delayed active response can never leave the tab marked
 * active after it was hidden or unloaded. Presence never unloads a model.
 */
export function useKllmSessionPresence(enabled = true): void {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const sessionChecked = useAuthStore((state) => state.sessionChecked);
  const sessionId = useBrowserSessionId();
  const lastInteractionRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!enabled || !sessionChecked || !isAuthenticated || !sessionId) return;

    let cancelled = false;
    lastInteractionRef.current = Date.now();

    let inFlightActiveController: AbortController | null = null;
    const queue = createPresenceHeartbeatQueue(async (active) => {
      if (cancelled) return;
      const controller = new AbortController();
      if (active) inFlightActiveController = controller;
      try {
        await api.sessionHeartbeat(sessionId, active, controller.signal);
      } finally {
        if (inFlightActiveController === controller) {
          inFlightActiveController = null;
        }
      }
    });
    const abortActiveHeartbeat = () => {
      const controller = inFlightActiveController;
      if (controller && !controller.signal.aborted) controller.abort();
    };
    const requestPresence = (active: boolean) => {
      // A newer deactivation supersedes an active request that may still be
      // in flight; the queue then sends the deactivation immediately.
      if (!active) abortActiveHeartbeat();
      queue.request(active);
    };

    const activeNow = () =>
      !document.hidden && isRecentlyInteractive(lastInteractionRef.current);

    const schedule = (delay: number) => {
      if (cancelled) return;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        requestPresence(activeNow());
        // A visibility change while the heartbeat was in flight clears the
        // timer; do not resurrect it from a callback that was already queued.
        if (!cancelled && !document.hidden) {
          schedule(KLLM_HEARTBEAT_INTERVAL_MS);
        }
      }, delay);
    };

    const onActivity = (event: Event) => {
      if (!isPresenceActivityEvent(event.type)) return;
      lastInteractionRef.current = Date.now();
    };

    const onVisibility = () => {
      if (document.hidden) {
        requestPresence(false);
        if (timerRef.current) {
          clearTimeout(timerRef.current);
          timerRef.current = null;
        }
      } else {
        lastInteractionRef.current = Date.now();
        requestPresence(true);
        schedule(KLLM_HEARTBEAT_INTERVAL_MS);
      }
    };

    const onPageHide = () => {
      requestPresence(false);
      void endBrowserPresence(sessionId, useAuthStore.getState().token);
    };

    const onPageShow = (event: PageTransitionEvent) => {
      if (document.hidden || event.persisted === false) return;
      lastInteractionRef.current = Date.now();
      requestPresence(true);
      schedule(KLLM_HEARTBEAT_INTERVAL_MS);
    };

    const activityEvents = ['pointerdown', 'keydown', 'wheel', 'touchstart', 'focus'];
    for (const type of activityEvents) {
      window.addEventListener(type, onActivity, { passive: true });
    }
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', onPageHide);
    window.addEventListener('pageshow', onPageShow);

    if (document.hidden) {
      requestPresence(false);
    } else {
      requestPresence(activeNow());
      schedule(KLLM_HEARTBEAT_INTERVAL_MS);
    }

    return () => {
      cancelled = true;
      abortActiveHeartbeat();
      queue.stop();
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      for (const type of activityEvents) {
        window.removeEventListener(type, onActivity);
      }
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', onPageHide);
      window.removeEventListener('pageshow', onPageShow);
      void endBrowserPresence(sessionId, useAuthStore.getState().token);
    };
  }, [enabled, isAuthenticated, sessionChecked, sessionId]);
}
