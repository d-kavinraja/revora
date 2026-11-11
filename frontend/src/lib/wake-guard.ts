/**
 * Coordinates the "backend is asleep" redirect.
 *
 * The dashboard layout and the global server overlay both probe health and
 * both used to call router.replace('/waking-up') independently. Two client
 * navigations racing each other abort route/chunk loads and surface as opaque
 * unhandled `ErrorEvent` rejections. Only the first caller for a given route
 * within a short window may start the redirect.
 */
const DEDUPE_WINDOW_MS = 3_000;

let lastPath: string | null = null;
let lastAt = 0;

export function claimWakeRedirect(pathname: string): boolean {
  const now = Date.now();
  if (lastPath === pathname && now - lastAt < DEDUPE_WINDOW_MS) {
    return false;
  }
  lastPath = pathname;
  lastAt = now;
  return true;
}

export function resetWakeRedirect(): void {
  lastPath = null;
  lastAt = 0;
}
