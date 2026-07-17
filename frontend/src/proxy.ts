import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function proxy(request: NextRequest) {
  const token = request.cookies.get('revora_auth_token')?.value;

  // Protect /dashboard and /settings routes
  if (request.nextUrl.pathname.startsWith('/dashboard') || request.nextUrl.pathname.startsWith('/settings') || request.nextUrl.pathname.startsWith('/repositories') || request.nextUrl.pathname.startsWith('/reviews')) {
    if (!token) {
      return NextResponse.redirect(new URL('/login', request.url));
    }
  }

  // Redirect /login to dashboard if already authenticated
  if (request.nextUrl.pathname.startsWith('/login') || request.nextUrl.pathname === '/') {
    if (token) {
      return NextResponse.redirect(new URL('/dashboard', request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico|revora-logo.png|.*\\.png$).*)'],
};
