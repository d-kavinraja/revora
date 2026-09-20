import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { isIndexableDeployment } from '@/lib/site';

/**
 * Routes that require a signed-in user. Unchanged behaviour: anonymous visitors are
 * sent to the sign-in page.
 */
const AUTHENTICATED_ROUTE_PREFIXES = [
  '/dashboard',
  '/settings',
  '/repositories',
  '/reviews',
];

/**
 * Routes that must never become search-index targets. Authenticated application screens,
 * the auth flow and the transient `/waking-up` status page are all private or useless to
 * a search user, so they answer with `X-Robots-Tag: noindex, nofollow`.
 *
 * This is done with a response header rather than a robots.txt disallow on purpose:
 * a disallowed URL can never be re-crawled, so Google would be unable to see a noindex
 * directive on it.
 */
const NON_INDEXABLE_ROUTE_PREFIXES = [
  ...AUTHENTICATED_ROUTE_PREFIXES,
  '/profile',
  '/guide',
  '/login',
  '/register',
  '/auth',
  '/waking-up',
];

function matchesPrefix(pathname: string, prefixes: string[]): boolean {
  return prefixes.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

/**
 * Applies noindex to private routes, and to every route of a non-production
 * deployment, so that a Vercel preview can never be indexed instead of - or alongside -
 * the production site.
 */
function withRobotsPolicy(response: NextResponse, pathname: string): NextResponse {
  const isPrivateRoute = matchesPrefix(pathname, NON_INDEXABLE_ROUTE_PREFIXES);

  if (!isIndexableDeployment() || isPrivateRoute) {
    response.headers.set('X-Robots-Tag', 'noindex, nofollow');
  }

  return response;
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get('revora_auth_token')?.value;

  // Protect application routes
  if (matchesPrefix(pathname, AUTHENTICATED_ROUTE_PREFIXES)) {
    if (!token) {
      return withRobotsPolicy(
        NextResponse.redirect(new URL('/login', request.url)),
        pathname
      );
    }
  }

  // Redirect /login to dashboard if already authenticated
  if (pathname.startsWith('/login') || pathname === '/') {
    if (token) {
      return withRobotsPolicy(
        NextResponse.redirect(new URL('/dashboard', request.url)),
        pathname
      );
    }
  }

  return withRobotsPolicy(NextResponse.next(), pathname);
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico|revora-logo.png|.*\\.png$).*)'],
};
