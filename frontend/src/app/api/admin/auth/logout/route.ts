import type { NextRequest } from 'next/server';

import { forwardAuthRequest } from '@/lib/auth-bff';

const ADMIN_SESSION_COOKIE = 'revora_admin_session';

function clearAdminCookie(headers: Headers, secure: boolean): void {
  const attributes = ['Path=/', 'HttpOnly', 'SameSite=Lax', 'Max-Age=0'];
  if (secure) attributes.push('Secure');
  headers.append(
    'Set-Cookie',
    `${ADMIN_SESSION_COOKIE}=; ${attributes.join('; ')}`,
  );
}

/** Revoke the backend session and always clear the first-party cookie. */
export async function POST(request: NextRequest) {
  const upstream = await forwardAuthRequest(request, '/admin/auth/logout', {
    method: 'POST',
    relayCookies: true,
  });
  const headers = new Headers(upstream.headers);
  clearAdminCookie(headers, request.nextUrl.protocol === 'https:');

  // A missing/expired session may make the backend return 401. Local cookie
  // deletion must still succeed so the browser cannot be trapped in a loop.
  const status = upstream.status === 401 ? 200 : upstream.status;
  const body = await upstream.text();
  return new Response(
    body || JSON.stringify({ status: 'logged_out' }),
    { status, headers },
  );
}
