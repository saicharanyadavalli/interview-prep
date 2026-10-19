import { NextResponse, type NextRequest } from 'next/server.js';
export const COGNITO_COOKIE_NAMES = {
  STATE: 'cognito_oauth_state',
  VERIFIER: 'cognito_pkce_verifier',
  NONCE: 'cognito_nonce',
  NEXT: 'cognito_oauth_next',
  ACCESS_TOKEN: 'cognito_access_token',
  REFRESH_TOKEN: 'cognito_refresh_token',
  ID_TOKEN: 'cognito_id_token',
} as const;

export const PROTECTED_ROUTES = [
  '/dashboard',
  '/profile',
  '/progress',
  '/revisit',
  '/solve',
  '/practice',
];

export const PUBLIC_ROUTES = [
  '/',
  '/login',
  '/signup',
  '/courses',
  '/dsa/leetcode',
  '/questions',
  '/auth',
  '/api',
];

/**
 * Checks unverified exp claim to ensure the JWT token has not expired.
 */
export function isTokenActive(token?: string | null): boolean {
  if (!token || typeof token !== 'string') return false;

  try {
    const parts = token.split('.');
    if (parts.length < 2) return false;

    let base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    while (base64.length % 4 !== 0) {
      base64 += '=';
    }

    const jsonString =
      typeof Buffer !== 'undefined'
        ? Buffer.from(base64, 'base64').toString('utf-8')
        : atob(base64);

    const payload = JSON.parse(jsonString);
    if (!payload || typeof payload !== 'object') return false;
    if (typeof payload.exp !== 'number') return false;

    const now = Math.floor(Date.now() / 1000);
    return payload.exp > now;
  } catch {
    return false;
  }
}

/**
 * Inspects cookies for an active, unexpired Amazon Cognito access or ID token.
 */
export function isUserAuthenticated(request: NextRequest): boolean {
  const accessToken = request.cookies.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value;
  const idToken = request.cookies.get(COGNITO_COOKIE_NAMES.ID_TOKEN)?.value;

  return isTokenActive(accessToken) || isTokenActive(idToken);
}

export async function proxy(request: NextRequest) {
  if (process.env.NEXT_PUBLIC_DISABLE_AUTH === 'true') {
    return NextResponse.next();
  }

  const pathname = request.nextUrl.pathname;

  // If auth code or token_hash arrives outside /auth/callback (e.g. at root /),
  // immediately forward to /auth/callback to perform the PKCE session exchange or OTP verification
  if (
    pathname !== '/auth/callback' &&
    (request.nextUrl.searchParams.has('code') || request.nextUrl.searchParams.has('token_hash'))
  ) {
    const url = request.nextUrl.clone();
    url.pathname = '/auth/callback';
    return NextResponse.redirect(url);
  }

  const isAuthenticated = isUserAuthenticated(request);

  // Handle /signup route by redirecting to /login in signup mode (or /dashboard if authenticated)
  if (pathname === '/signup') {
    const url = request.nextUrl.clone();
    if (isAuthenticated) {
      url.pathname = '/dashboard';
      url.search = '';
    } else {
      url.pathname = '/login';
      url.searchParams.set('mode', 'signup');
    }
    return NextResponse.redirect(url);
  }

  const isProtected = PROTECTED_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`)
  );

  // If unauthenticated user requests a protected route, preserve destination and redirect to /login
  if (isProtected && !isAuthenticated) {
    const next = request.nextUrl.pathname + request.nextUrl.search;
    const url = request.nextUrl.clone();
    url.pathname = '/login';
    url.search = `?next=${encodeURIComponent(next)}`;
    return NextResponse.redirect(url);
  }

  // If authenticated user visits /login or root /, redirect to /dashboard
  if (isAuthenticated && (pathname === '/login' || pathname === '/')) {
    const url = request.nextUrl.clone();
    url.pathname = '/dashboard';
    url.search = '';
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const middleware = proxy;

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
