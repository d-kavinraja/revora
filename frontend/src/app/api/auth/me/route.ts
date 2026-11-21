import type { NextRequest } from 'next/server';

import { forwardAuthRequest } from '@/lib/auth-bff';

/**
 * Same-origin BFF proxy for session confirmation (GET /auth/me).
 *
 * The durable session is the backend-issued HttpOnly cookie, which the
 * exchange BFF relays as a first-party cookie on the frontend host. Confirming
 * the session must therefore go through a same-origin route so that cookie is
 * actually attached: a direct cross-origin call to the backend would drop it
 * and falsely report "session could not be confirmed" even though the
 * exchange succeeded. This route forwards the cookie and relays the response
 * (status + body) verbatim so the client can distinguish a real 401 from a
 * transient network failure.
 */
export async function GET(request: NextRequest) {
  return forwardAuthRequest(request, '/auth/me', { method: 'GET' });
}
