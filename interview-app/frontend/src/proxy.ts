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

  const supabaseUrl = CONFIG.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || '';
  const supabaseAnonKey = CONFIG.SUPABASE_ANON_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '';

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
