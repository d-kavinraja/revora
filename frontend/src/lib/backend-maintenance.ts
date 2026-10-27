import { backendApiBase } from '@/lib/backend-origin';

/**
 * BFF-side maintenance short-circuit (§12.3).
 *
 * The backend already answers user auth routes with 503 and mints no
 * cookies, but the BFF routes must not even attempt to relay a session:
 * check `/platform/status` first (5s in-process cache, fail-open) and
 * return the same `{"code":"maintenance"}` payload before any upstream
 * call or Set-Cookie handling runs.
 */
const CACHE_TTL_MS = 5_000;
let cache: { enabled: boolean; at: number } | null = null;

export async function isBackendInMaintenance(): Promise<boolean> {
  const now = Date.now();
  if (cache && now - cache.at < CACHE_TTL_MS) {
    return cache.enabled;
  }

  try {
    const response = await fetch(`${backendApiBase()}/platform/status`, {
      cache: 'no-store',
      headers: { accept: 'application/json' },
      signal: AbortSignal.timeout(2_000),
    });
    if (!response.ok) {
      throw new Error(`platform status returned ${response.status}`);
    }
    const payload = (await response.json()) as {
      maintenance?: { enabled?: boolean };
    };
    const enabled = payload?.maintenance?.enabled === true;
    cache = { enabled, at: now };
    return enabled;
  } catch {
    // Fail open: an unreachable status endpoint must not brick sign-in.
    cache = { enabled: false, at: now };
    return false;
  }
}

export function maintenanceUnavailableResponse(): Response {
  return Response.json({ code: 'maintenance' }, { status: 503 });
}
