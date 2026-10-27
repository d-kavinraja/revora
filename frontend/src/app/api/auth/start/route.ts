import type { NextRequest } from 'next/server';

import { backendApiBase } from '@/lib/backend-origin';
import {
  isBackendInMaintenance,
  maintenanceUnavailableResponse,
} from '@/lib/backend-maintenance';
import { relaySetCookies } from '@/lib/bff-cookies';

/**
 * Same-origin BFF proxy for minting the OAuth login-CSRF state.
 *
 * The backend sets the oauth_state cookie on its response; relaying it
 * through here (normalized to first-party SameSite=Lax) makes the browser
 * actually store it on http://localhost, so the exchange can prove this
 * browser started the flow instead of silently skipping verification.
 */
export async function GET(request: NextRequest) {
  // Maintenance short-circuit (§12.3): same 503 payload, no cookie relay.
  if (await isBackendInMaintenance()) {
    return maintenanceUnavailableResponse();
  }

  // Normalized to .../api/v1 regardless of BACKEND_ORIGIN shape (bare
  // origin vs suffixed URL) — a bare origin here previously produced
  // upstream /auth/... paths that FastAPI answers with 404.
  const apiBase = backendApiBase();

  const cookieHeader = request.headers.get('cookie');

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBase}/auth/oauth/start`, {
      headers: cookieHeader ? { cookie: cookieHeader } : {},
      signal: AbortSignal.timeout(10_000),
      cache: 'no-store',
    });
  } catch {
    return Response.json(
      { detail: 'Could not reach the authentication backend.' },
      { status: 502 }
    );
  }

  const text = await upstream.text();
  const headers = new Headers({ 'Content-Type': 'application/json' });
  const names = relaySetCookies(upstream.headers, headers);
  console.log(
    `[BFF] oauth-start upstream=${upstream.status} setCookies=${names.length} [${names.join(',')}]`
  );
  return new Response(text || '{}', { status: upstream.status, headers });
}
