'use client';

import { useCallback, useState } from 'react';

const SESSION_KEY = 'revora_onboarding_shown_v1';

function shouldAutoShow(autoShow: boolean, dismissed: boolean): boolean {
  if (!autoShow || dismissed) return false;
  try {
    const params = new URLSearchParams(
      typeof window !== 'undefined' ? window.location.search : '',
    );
    const forced =
      params.get('tour') === '1' || params.get('onboarding') === '1';
    const alreadyShown =
      typeof window !== 'undefined' &&
      sessionStorage.getItem(SESSION_KEY) === '1';
    return forced || !alreadyShown;
  } catch {
    return false;
  }
}

function markShown() {
  try {
    sessionStorage.setItem(SESSION_KEY, '1');
  } catch {
    /* storage unavailable */
  }
}

/**
 * Manages onboarding tour visibility.
 *
 * - Auto-shows once per browser session (sessionStorage), so a fresh login or
 *   a new tab triggers it, but a refresh within the same session does not
 *   re-trigger it automatically.
 * - Never reads or writes a permanent localStorage dismissal flag, so stale
 *   "dismissed" state cannot suppress the tour forever.
 * - The tour can always be reopened via `openTour()` regardless of dismissal.
 */
export function useOnboarding(autoShow = true) {
  const [open, setOpen] = useState(false);
  const [autoDismissed, setAutoDismissed] = useState(false);

  // Auto-show is computed during render (not in an effect) so the tour mounts
  // as soon as the user is authenticated, without cascading renders.
  if (shouldAutoShow(autoShow, autoDismissed) && !open) {
    markShown();
    setOpen(true);
  }

  const openTour = useCallback(() => setOpen(true), []);
  const closeTour = useCallback(() => {
    setAutoDismissed(true);
    setOpen(false);
  }, []);

  return { open, openTour, closeTour };
}
