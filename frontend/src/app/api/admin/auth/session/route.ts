import type { NextRequest } from 'next/server';

import { forwardAuthRequest } from '@/lib/auth-bff';

/** Read-only confirmation of the existing opaque admin session. */
export async function GET(request: NextRequest) {
  return forwardAuthRequest(request, '/admin/auth/session', { method: 'GET' });
}
