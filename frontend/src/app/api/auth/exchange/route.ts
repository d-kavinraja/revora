import type { NextRequest } from 'next/server';

import { backendApiBase } from '@/lib/backend-origin';
import {
  isBackendInMaintenance,
  maintenanceUnavailableResponse,
} from '@/lib/backend-maintenance';
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
  // Maintenance short-circuit (§12.3): refuse BEFORE reading the body or
  // touching cookies — no session can be minted while the switch is on.
  if (await isBackendInMaintenance()) {
    return maintenanceUnavailableResponse();
  }

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

  const apiBase = backendApiBase();

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
    `[BFF] exchange upstream=${upstream.status} bodyLen=${text.length} setCookies=${names.length} [${names.join(',')}]`
  );
  // Defensive fallback: never relay an empty body for an error response,
  // otherwise the client cannot surface the backend's explanation.
  let responseBody = text;
  if (!responseBody && !upstream.ok) {
    responseBody = JSON.stringify({
      detail:
        upstream.status === 403
          ? 'Your account has been disabled. Please contact the administrator for assistance.'
          : `Request failed with status ${upstream.status}.`,
      ...(upstream.status === 403 ? { code: 'account_disabled' } : {}),
    });
  }
  return new Response(responseBody || '{}', { status: upstream.status, headers });
}
