import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { backendApiBase } from '@/lib/backend-origin';
import { isIndexableDeployment } from '@/lib/site';
import { isSafeInternalPath } from '@/lib/safe-redirect';

/**
 * Routes that require a signed-in user. Unchanged behaviour: anonymous visitors are
 * sent to the sign-in page.
 */
const AUTHENTICATED_ROUTE_PREFIXES = [
  '/dashboard',
  '/settings',
  '/repositories',
  '/reviews',
  '/model-lab',
];

/**
 * Maintenance redirect exemptions (§12.4): the admin console must stay
 * reachable for recovery, and /maintenance itself must never self-redirect.
 * Static assets are already excluded by the matcher below.
 */
const MAINTENANCE_EXEMPT_PREFIXES = ['/admin', '/maintenance'];

/**
 * Edge-side maintenance lookup cache. The backend serves status through its
 * own 5s TTL cache, so this only bounds extra round-trips (staleness bound
 * stays ≤ 5s either way). Fails open — a flaky backend must never trap the
 * whole site on /maintenance.
 */
const MAINTENANCE_CACHE_TTL_MS = 5_000;
let maintenanceCache: { enabled: boolean; at: number } | null = null;

async function isMaintenanceActive(): Promise<boolean> {
  const now = Date.now();
  if (maintenanceCache && now - maintenanceCache.at < MAINTENANCE_CACHE_TTL_MS) {
    return maintenanceCache.enabled;
  }

  try {
    const response = await fetch(`${backendApiBase()}/platform/status`, {
      cache: 'no-store',
      headers: { accept: 'application/json' },
      signal: AbortSignal.timeout(2_000),
    });
    if (!response.ok) {
      throw new Error(`platform status returned ${response.status}`);
    }
    const payload = (await response.json()) as {
      maintenance?: { enabled?: boolean };
    };
    const enabled = payload?.maintenance?.enabled === true;
    maintenanceCache = { enabled, at: now };
    return enabled;
  } catch {
    maintenanceCache = { enabled: false, at: now };
    return false;
  }
}

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
  // Admin control center + public maintenance page. Direct-URL access only;
  // deliberately NOT in AUTHENTICATED_ROUTE_PREFIXES — the user-cookie gate
  // is irrelevant here because the admin console self-guards server-side
  // (every admin API call requires a valid admin session).
  '/admin',
  '/maintenance',
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

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get('revora_auth_token')?.value;

  // Global maintenance gate (§12.4): while the switch is on, every page load
  // goes to /maintenance — except the admin console (recovery path) and the
  // maintenance page itself. Runs before the auth gate so signed-in users
  // land on the status page instead of a blocked dashboard.
  if (!matchesPrefix(pathname, MAINTENANCE_EXEMPT_PREFIXES)) {
    if (await isMaintenanceActive()) {
      return withRobotsPolicy(
        NextResponse.redirect(new URL('/maintenance', request.url)),
        pathname
      );
    }
  }

  // Protect application routes
  if (matchesPrefix(pathname, AUTHENTICATED_ROUTE_PREFIXES)) {
    if (!token) {
      // Preserve the originally requested path so the login flow can return
      // the user here (instead of always landing on /dashboard).
      const loginUrl = new URL('/login', request.url);
      loginUrl.searchParams.set('redirect', pathname);
      return withRobotsPolicy(NextResponse.redirect(loginUrl), pathname);
    }
  }

  // Redirect /login to dashboard if already authenticated
  if (pathname.startsWith('/login') || pathname === '/') {
    if (token) {
      // Honour a preserved destination when it is a safe internal path;
      // otherwise fall back to the dashboard.
      const requested = request.nextUrl.searchParams.get('redirect');
      const destination = isSafeInternalPath(requested) ? requested : '/dashboard';
      return withRobotsPolicy(
        NextResponse.redirect(new URL(destination, request.url)),
        pathname
      );
    }
  }

  return withRobotsPolicy(NextResponse.next(), pathname);
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico|revora-logo.png|.*\\.png$).*)'],
};
