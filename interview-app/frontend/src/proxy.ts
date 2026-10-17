import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import { CONFIG } from '@/lib/config';

const PROTECTED_ROUTES = [
  "/dashboard",
  "/practice",
  "/questions",
  "/solve",
  "/profile",
  "/progress",
  "/revisit",
  "/dsa"
];

export async function proxy(request: NextRequest) {
  if (process.env.NEXT_PUBLIC_DISABLE_AUTH === "true") {
    return NextResponse.next();
  }

  let supabaseResponse = NextResponse.next({
    request: {
      headers: request.headers,
    },
  });

  const supabaseUrl = (process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || CONFIG.SUPABASE_URL || '').trim().replace(/^["']|["']$/g, '');
  const supabaseAnonKey = (process.env.SUPABASE_ANON_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || CONFIG.SUPABASE_ANON_KEY || '').trim().replace(/^["']|["']$/g, '');

  if (!supabaseUrl || !supabaseAnonKey) {
    return supabaseResponse;
  }

  const supabase = createServerClient(
    supabaseUrl,
    supabaseAnonKey,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => {
            request.cookies.set(name, value);
          });

          supabaseResponse = NextResponse.next({
            request: {
              headers: request.headers,
            },
          });

          cookiesToSet.forEach(({ name, value, options }) => {
            supabaseResponse.cookies.set(name, value, options);
          });
        },
      },
    }
  );

  // Authenticate & refresh user token using getUser() per Supabase SSR best practices
  let user = null;
  try {
    const {
      data,
      error,
    } = await supabase.auth.getUser();
    if (!error && data) {
      user = data.user;
    }
  } catch (err) {
    console.warn('Supabase auth.getUser() check failed in proxy:', err);
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

  // Gracefully handle /signup route by redirecting to /login in signup mode
  if (pathname === '/signup') {
    const url = request.nextUrl.clone();
    url.pathname = '/login';
    url.searchParams.set('mode', 'signup');
    return NextResponse.redirect(url);
  }

  const isProtected = PROTECTED_ROUTES.some(route => pathname.startsWith(route));

  if (isProtected && !user) {
    const url = request.nextUrl.clone();
    url.pathname = '/login';
    return NextResponse.redirect(url);
  }

  if (user && (pathname === '/login' || pathname === '/')) {
    const url = request.nextUrl.clone();
    url.pathname = '/dashboard';
    return NextResponse.redirect(url);
  }

  return supabaseResponse;
}

export const middleware = proxy;

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
