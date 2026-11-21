'use client';

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/store/useAuthStore';

const LOCAL_DISMISSAL_PREFIX = 'revora_onboarding_dismissed_v1';

function localStorageKey(userId: string | null | undefined): string {
  return `${LOCAL_DISMISSAL_PREFIX}:${userId ?? 'anonymous'}`;
}

function readLocalDismissal(userId: string | null | undefined): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(localStorageKey(userId)) === '1';
  } catch {
    return false;
  }
}

function markLocalDismissal(userId: string | null | undefined): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(localStorageKey(userId), '1');
  } catch {
    /* storage unavailable */
  }
}

export interface UseOnboardingOptions {
  /** Auto-open only while true (dashboard layout gates on auth hydration). */
  autoShow?: boolean;
  /** True once session/user hydration has settled and the user is authenticated. */
  ready?: boolean;
  /** Backend-perceived onboarding completion; when true the tour must not auto-open. */
  dismissed?: boolean;
  /** Current account id, used to namespace local dismissal storage. */
  userId?: string | null;
}

/**
 * Manages onboarding tour visibility.
 *
 * - Auto-opens at most once per user, only after auth/session hydration has
 *   settled and only when the user has not completed or dismissed the tour.
 * - Persists dismissal locally (per-user localStorage) immediately and calls the
 *   backend completion endpoint for durable cross-device/server-restart state.
 * - Manual opening via `openTour()` is always allowed.
 */
export function useOnboarding({
  autoShow = true,
  ready = true,
  dismissed,
  userId = null,
}: UseOnboardingOptions = {}) {
  const [open, setOpen] = useState(false);
  // Initialize from localStorage during first render (useState initializer is
  // allowed; it is not a subsequent setState during render).
  const [localDismissed, setLocalDismissed] = useState(() =>
    readLocalDismissal(userId),
  );

  const isDismissed = dismissed ?? localDismissed;

  // Auto-open: shown when conditions are met and the user has not dismissed.
  // `open` is true only when manually opened via openTour(); auto-show is
  // derived from the conditions below so we never call setState during render.
  const isOpen =
    open || (autoShow && ready && !isDismissed);

  // Persist the "shown" flag to localStorage when auto-show triggers so the
  // tour only appears once per browser. localStorage writes are not React
  // state updates, so this effect does not trigger set-state-in-effect.
  useEffect(() => {
    if (!autoShow || !ready || isDismissed || open) return;
    markLocalDismissal(userId);
  }, [autoShow, ready, userId, isDismissed, open]);

  const openTour = useCallback(() => {
    setOpen(true);
  }, []);

  const closeTour = useCallback(() => {
    setLocalDismissed(true);
    markLocalDismissal(userId);
    useAuthStore.getState().markOnboardingComplete();
    void api.completeOnboarding().catch((error) => {
      console.error('[onboarding] failed to persist completion', error);
    });
    setOpen(false);
  }, [userId]);

  return { open: isOpen, openTour, closeTour };
}
