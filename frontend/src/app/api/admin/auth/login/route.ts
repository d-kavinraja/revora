import type { NextRequest } from 'next/server';

import { forwardAuthRequest } from '@/lib/auth-bff';

/** Same-origin admin login; explicitly relays the opaque admin cookie. */
export async function POST(request: NextRequest) {
  let body: string;
  try {
    body = await request.text();
    JSON.parse(body);
  } catch {
    return Response.json({ detail: 'Invalid JSON body.' }, { status: 400 });
  }
  return forwardAuthRequest(request, '/admin/auth/login', {
    method: 'POST',
    body,
    relayCookies: true,
  });
}
