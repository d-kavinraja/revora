/**
 * Shared cookie-relay helpers for the same-origin auth BFF routes.
 *
 * With the BFF pattern every cookie is first-party (the browser only ever
 * talks to the frontend host; the backend host never touches it). The
 * backend still stamps SameSite=None (its cross-origin design), which
 * browsers reject over plain-HTTP localhost. Normalizing to SameSite=Lax
 * at the relay boundary keeps the cookies storable on http://localhost
 * while remaining CSRF-safe (Lax still blocks true cross-site sends).
 */

/** Split a combined Set-Cookie value on commas that start a new cookie. */
function splitSetCookie(combined: string): string[] {
  return combined
    .split(/,(?=[^;,=\s]+\s*=)/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function extractSetCookies(headers: Headers): string[] {
  if (typeof headers.getSetCookie === 'function') {
    try {
      const direct = headers.getSetCookie();
      if (direct.length > 0) return direct;
    } catch {
      // fall through to the raw-header fallback below
    }
  }
  const raw = headers.get('set-cookie');
  return raw ? splitSetCookie(raw) : [];
}

/** Rewrite SameSite=None to SameSite=Lax (first-party normalization). */
export function firstPartyCookie(cookie: string): string {
  return cookie.replace(/;\s*SameSite=None/i, '; SameSite=Lax');
}

/**
 * Append upstream Set-Cookie headers (first-party normalized) to the
 * outgoing response. Returns cookie names only (never values) for logging.
 */
export function relaySetCookies(
  upstream: Headers,
  target: Headers
): string[] {
  const names: string[] = [];
  for (const cookie of extractSetCookies(upstream)) {
    const normalized = firstPartyCookie(cookie);
    target.append('Set-Cookie', normalized);
    names.push(normalized.split('=')[0]);
  }
  return names;
}
