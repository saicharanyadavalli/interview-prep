import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import { CONFIG } from '@/lib/config'
import {
  getAllowedOrigins,
  validateRedirectDestination,
  CANONICAL_AWS_ORIGIN,
} from '@/utils/auth-redirect'

export async function GET(request: Request) {
  const requestUrl = new URL(request.url)
  const searchParams = requestUrl.searchParams
  const code = searchParams.get('code')
  const token_hash = searchParams.get('token_hash')
  const type = searchParams.get('type')
  const rawNext = searchParams.get('next')

  // Resolve trusted allowed origins (including configured AUTH_REDIRECT_URL)
  const allowedOrigins = getAllowedOrigins(process.env.AUTH_REDIRECT_URL)

  // Validate and sanitize destination to strictly prevent open redirects (defaults to /dashboard)
  const safeNext = validateRedirectDestination(rawNext, allowedOrigins)

  // ── Resolve authoritative deployment origin ────────────────────────────────
  //
  // Priority order (hard stops — no fallthrough once one succeeds):
  //   1. AUTH_REDIRECT_URL env var (server-side, set in .env and Docker runtime)
  //   2. FRONTEND_URL env var (server-side, set in .env and Docker runtime)
  //   3. localhost / 127.0.0.1 request origin (local development only)
  //   4. X-Forwarded-Host header IF AND ONLY IF it matches an allowed origin
  //   5. CANONICAL_AWS_ORIGIN (non-negotiable production fallback)
  //
  // Security invariant: forwarded headers are only consulted when NEITHER
  // AUTH_REDIRECT_URL nor FRONTEND_URL is configured (local dev only).
  // In production on EC2, AUTH_REDIRECT_URL is always set so we never reach (4).
  // ─────────────────────────────────────────────────────────────────────────────
  let baseOrigin = CANONICAL_AWS_ORIGIN
  let originSource = 'canonical-fallback'

  if (process.env.AUTH_REDIRECT_URL) {
    try {
      const p = new URL(process.env.AUTH_REDIRECT_URL)
      if ((p.protocol === 'http:' || p.protocol === 'https:') && p.hostname) {
        baseOrigin = p.origin
        originSource = 'AUTH_REDIRECT_URL'
      } else {
        console.error(
          '[auth/callback] AUTH_REDIRECT_URL has invalid protocol or missing hostname; using canonical AWS origin.'
        )
      }
    } catch (_) {
      console.error('[auth/callback] AUTH_REDIRECT_URL is malformed; using canonical AWS origin.')
    }
  } else if (process.env.FRONTEND_URL) {
    try {
      const p = new URL(process.env.FRONTEND_URL)
      if ((p.protocol === 'http:' || p.protocol === 'https:') && p.hostname) {
        baseOrigin = p.origin
        originSource = 'FRONTEND_URL'
      } else {
        console.error(
          '[auth/callback] FRONTEND_URL has invalid protocol or missing hostname; using canonical AWS origin.'
        )
      }
    } catch (_) {
      console.error('[auth/callback] FRONTEND_URL is malformed; using canonical AWS origin.')
    }
  } else {
    // Neither explicit env var is set — local development path only.
    // Allow localhost origins. For all other cases, validate forwarded headers
    // strictly against the allowlist before accepting them.
    if (requestUrl.hostname === 'localhost' || requestUrl.hostname === '127.0.0.1') {
      baseOrigin = requestUrl.origin
      originSource = 'localhost-request'
    } else {
      const forwardedHost = request.headers.get('x-forwarded-host') || request.headers.get('host')
      const forwardedProto =
        request.headers.get('x-forwarded-proto') ||
        requestUrl.protocol.replace(':', '') ||
        'http'
      if (forwardedHost) {
        try {
          const candidateOrigin = new URL(`${forwardedProto}://${forwardedHost}`).origin
          if (allowedOrigins.some((o) => o.toLowerCase() === candidateOrigin.toLowerCase())) {
            baseOrigin = candidateOrigin
            originSource = 'x-forwarded-host (allowlisted)'
          } else {
            console.warn(
              `[auth/callback] X-Forwarded-Host "${forwardedHost}" is not in the allowed origins list. Using canonical AWS origin.`
            )
          }
        } catch (_) {
          console.warn('[auth/callback] Could not parse X-Forwarded-Host; using canonical AWS origin.')
        }
      }
    }
  }

  if (originSource === 'canonical-fallback') {
    console.info(
      '[auth/callback] No explicit origin configuration found; using canonical AWS origin as safe default.'
    )
  }

  // Handle PKCE code exchange or Email OTP verification
  if (code || (token_hash && type)) {
    if (!CONFIG.SUPABASE_URL || !CONFIG.SUPABASE_ANON_KEY) {
      console.error('Auth callback error: Supabase environment variables missing.')
      const url = new URL('/login?error=env-missing', baseOrigin)
      return NextResponse.redirect(url)
    }

    const redirectTarget = new URL(safeNext, baseOrigin)
    const response = NextResponse.redirect(redirectTarget)
    const cookieStore = await cookies()

    const supabase = createServerClient(
      CONFIG.SUPABASE_URL,
      CONFIG.SUPABASE_ANON_KEY,
      {
        cookies: {
          getAll() {
            return cookieStore.getAll()
          },
          setAll(cookiesToSet) {
            try {
              cookiesToSet.forEach(({ name, value, options }) => {
                cookieStore.set(name, value, options)
                response.cookies.set(name, value, options)
              })
            } catch (error) {
              // Ignore if called from a context where cookies cannot be set
            }
          },
        },
      }
    )

    if (token_hash && type) {
      const { error } = await supabase.auth.verifyOtp({
        type: type as any,
        token_hash,
      })
      if (!error) {
        return response
      }
      console.error('Auth callback OTP verify error:', error.message)
    } else if (code) {
      const { error } = await supabase.auth.exchangeCodeForSession(code)
      if (!error) {
        return response
      }
      console.error('Auth callback code exchange error:', error.message)
    }
  }

  const errorDesc = searchParams.get('error_description') || searchParams.get('error')
  const errorQuery = errorDesc ? `?error=${encodeURIComponent(errorDesc)}` : '?error=auth-code-error'
  const url = new URL(`/login${errorQuery}`, baseOrigin)
  return NextResponse.redirect(url)
}
