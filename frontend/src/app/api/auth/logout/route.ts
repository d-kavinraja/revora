import type { NextRequest } from 'next/server';

import { relaySetCookies } from '@/lib/bff-cookies';

/**
 * Same-origin BFF proxy for logout.
 *
 * Forwards the browser's cookies to the backend /auth/logout (which revokes
 * every session by bumping token_version) and relays the deletion cookie
 * first-party. Additionally — and crucially — it ALWAYS emits its own
 * first-party deletion for the session cookie, so logout clears it even when
 * the session is already invalid and the backend returns 401 (a case where
 * the backend's own delete never runs, which would otherwise leave a stale
 * token that the edge gate keeps redirecting back into the app).
 */

const SESSION_COOKIE_NAME = 'revora_auth_token';

function clearSessionCookie(headers: Headers, secure: boolean): void {
  const attrs = ['Path=/', 'HttpOnly', 'SameSite=Lax', 'Max-Age=0'];
  if (secure) attrs.push('Secure');
  headers.append('Set-Cookie', `${SESSION_COOKIE_NAME}=; ${attrs.join('; ')}`);
}

export async function POST(request: NextRequest) {
  const apiBase =
    process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

  const cookieHeader = request.headers.get('cookie');
  const secure = request.nextUrl.protocol === 'https:';

  const headers = new Headers({ 'Content-Type': 'application/json' });

  let upstream: Response | null = null;
  try {
    upstream = await fetch(`${apiBase}/auth/logout`, {
      method: 'POST',
      headers: cookieHeader ? { cookie: cookieHeader } : {},
      signal: AbortSignal.timeout(10_000),
      cache: 'no-store',
    });
  } catch {
    // Backend unreachable: still clear the local cookie below so the client
    // is never trapped in a signed-in shell.
    upstream = null;
  }

  if (upstream) {
    const names = relaySetCookies(upstream.headers, headers);
    console.log(
      `[BFF] logout upstream=${upstream.status} relayed=${names.length}`
    );
  } else {
    console.log('[BFF] logout upstream=unreachable (clearing cookie locally)');
  }

  // Guarantee first-party deletion regardless of the upstream outcome.
  clearSessionCookie(headers, secure);

  const body = upstream ? await upstream.text() : '';
  const status = upstream?.status ?? 200;
  return new Response(body || JSON.stringify({ status: 'logged_out' }), {
    status,
    headers,
  });
}
