import type { NextRequest } from 'next/server';

import { relaySetCookies } from '@/lib/bff-cookies';

/**
 * Same-origin BFF proxy for the GitHub OAuth code exchange.
 *
 * The browser POSTs {code, state, redirect_uri} here (localhost:3000 — no
 * CORS, no cross-origin cookie quirks); the server forwards to the backend
 * /auth/github with the browser's cookies (oauth_state CSRF binding) and
 * relays the response, including every Set-Cookie header (normalized to
 * first-party SameSite=Lax), so the session cookie lands on localhost:3000
 * where the edge gate (proxy.ts) can see it.
 */
export async function POST(request: NextRequest) {
  let payload: { code?: unknown; state?: unknown; redirect_uri?: unknown };
  try {
    payload = await request.json();
  } catch {
    return Response.json({ detail: 'Invalid JSON body.' }, { status: 400 });
  }

  if (typeof payload.code !== 'string' || !payload.code) {
    return Response.json(
      { detail: 'Missing GitHub authorization code.' },
      { status: 400 }
    );
  }

  const apiBase =
    process.env.BACKEND_ORIGIN ||
    process.env.NEXT_PUBLIC_API_URL ||
    'http://localhost:8000/api/v1';

  const body = JSON.stringify({
    code: payload.code,
    state: typeof payload.state === 'string' ? payload.state : undefined,
    redirect_uri:
      typeof payload.redirect_uri === 'string'
        ? payload.redirect_uri
        : undefined,
  });

  const cookieHeader = request.headers.get('cookie');

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBase}/auth/github`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(cookieHeader ? { cookie: cookieHeader } : {}),
      },
      body,
      signal: AbortSignal.timeout(30_000),
      cache: 'no-store',
    });
  } catch {
    return Response.json(
      {
        detail:
          'Could not reach the authentication backend. Ensure it is running on port 8000.',
      },
      { status: 502 }
    );
  }

  const text = await upstream.text();
  const headers = new Headers({ 'Content-Type': 'application/json' });
  // Relay every Set-Cookie (session set + oauth_state single-use burn).
  const names = relaySetCookies(upstream.headers, headers);
  // Server-side observability: cookie names only, never values.
  console.log(
    `[BFF] exchange upstream=${upstream.status} setCookies=${names.length} [${names.join(',')}]`
  );
  return new Response(text || '{}', { status: upstream.status, headers });
}
