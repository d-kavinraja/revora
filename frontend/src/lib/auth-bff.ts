import { backendApiBase } from '@/lib/backend-origin';
import { relaySetCookies } from '@/lib/bff-cookies';

interface AuthForwardOptions {
  method: 'GET' | 'POST';
  body?: string;
  relayCookies?: boolean;
  timeoutMs?: number;
}

/**
 * Forward one fixed authentication endpoint to the backend.
 *
 * Callers provide a source-controlled path (never user input). Only the
 * cookie, content type and user agent needed by the auth endpoints are sent;
 * secrets are never logged and redirects are refused.
 */
export async function forwardAuthRequest(
  request: Request,
  upstreamPath: string,
  {
    method,
    body,
    relayCookies = false,
    timeoutMs = 30_000,
  }: AuthForwardOptions,
): Promise<Response> {
  const cookie = request.headers.get('cookie');
  const userAgent = request.headers.get('user-agent');
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };
  if (cookie) headers.cookie = cookie;
  if (userAgent) headers['user-agent'] = userAgent;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let upstream: Response;
  try {
    upstream = await fetch(`${backendApiBase()}${upstreamPath}`, {
      method,
      headers,
      body,
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch {
    return Response.json(
      { detail: 'Could not reach the authentication backend.' },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers({
    'Content-Type': upstream.headers.get('content-type') ?? 'application/json',
    'Cache-Control': 'no-store',
  });
  if (relayCookies) relaySetCookies(upstream.headers, responseHeaders);
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: responseHeaders,
  });
}
