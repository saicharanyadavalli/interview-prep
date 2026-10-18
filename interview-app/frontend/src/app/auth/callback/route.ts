import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import { CONFIG } from '@/lib/config'
import {
  COGNITO_COOKIE_NAMES,
  exchangeCodeForTokens,
  decodeIdTokenClaims,
  getCognitoConfig,
} from '@/lib/cognito'
import {
  getAllowedOrigins,
  validateRedirectDestination,
  cleanEnvValue,
  CANONICAL_AWS_ORIGIN,
} from '@/utils/auth-redirect'

export const dynamic = 'force-dynamic'

function getInternalBackendUrl(): string {
  const envUrl = process.env.BACKEND_INTERNAL_URL || process.env.NEXT_PUBLIC_API_BASE_URL
  if (envUrl && envUrl.startsWith('http')) {
    return envUrl.replace(/\/api\/backend\/?$/, '')
  }
  return 'http://127.0.0.1:8000'
}

export async function GET(request: Request) {
  let baseOrigin = CANONICAL_AWS_ORIGIN

  try {
    const requestUrl = new URL(request.url)
    const searchParams = requestUrl.searchParams
    const code = searchParams.get('code')
    const state = searchParams.get('state')
    const errorParam = searchParams.get('error')
    const errorDescription = searchParams.get('error_description')
    const token_hash = searchParams.get('token_hash')
    const type = searchParams.get('type')
    const rawNextQuery = searchParams.get('next')

    const cleanAuthRedirect = cleanEnvValue(process.env.AUTH_REDIRECT_URL)
    const cleanFrontendUrl = cleanEnvValue(process.env.FRONTEND_URL)

    // Resolve trusted allowed origins (including configured AUTH_REDIRECT_URL)
    const allowedOrigins = getAllowedOrigins(cleanAuthRedirect)

    // ── Resolve authoritative deployment origin ────────────────────────────────
    if (cleanAuthRedirect) {
      try {
        const p = new URL(cleanAuthRedirect)
        if ((p.protocol === 'http:' || p.protocol === 'https:') && p.hostname) {
          baseOrigin = p.origin
        }
      } catch (_) {}
    } else if (cleanFrontendUrl) {
      try {
        const p = new URL(cleanFrontendUrl)
        if ((p.protocol === 'http:' || p.protocol === 'https:') && p.hostname) {
          baseOrigin = p.origin
        }
      } catch (_) {}
    } else {
      if (requestUrl.hostname === 'localhost' || requestUrl.hostname === '127.0.0.1') {
        baseOrigin = requestUrl.origin
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
            }
          } catch (_) {}
        }
      }
    }

    const cookieStore = await cookies()

    // Handle OAuth error passed by identity provider / Cognito
    if (errorParam || errorDescription) {
      const errMessage = errorDescription || errorParam || 'OAuth authentication failed.'
      console.error('[auth/callback] Provider error:', errMessage)
      const redirectUrl = new URL(`/login?error=${encodeURIComponent(errMessage)}`, baseOrigin)
      const res = NextResponse.redirect(redirectUrl)
      // Clear temporary OAuth cookies
      res.cookies.delete(COGNITO_COOKIE_NAMES.STATE)
      res.cookies.delete(COGNITO_COOKIE_NAMES.VERIFIER)
      res.cookies.delete(COGNITO_COOKIE_NAMES.NONCE)
      res.cookies.delete(COGNITO_COOKIE_NAMES.NEXT)
      return res
    }

    // Determine target redirect destination
    const rawNext = rawNextQuery || cookieStore.get(COGNITO_COOKIE_NAMES.NEXT)?.value || '/dashboard'
    const safeNext = validateRedirectDestination(rawNext, allowedOrigins)

    const isSecure = baseOrigin.startsWith('https:')

    // ── Cognito OAuth PKCE Flow ─────────────────────────────────────────────
    const storedState = cookieStore.get(COGNITO_COOKIE_NAMES.STATE)?.value
    const storedVerifier = cookieStore.get(COGNITO_COOKIE_NAMES.VERIFIER)?.value

    // If PKCE verifier or state is present, or if state param was supplied, process Cognito flow
    if (code && (storedVerifier || storedState || state)) {
      if (!storedState || !state || storedState !== state) {
        console.error('[auth/callback] State validation failed. Possible CSRF attack or expired session.')
        const errUrl = new URL('/login?error=invalid_state', baseOrigin)
        const res = NextResponse.redirect(errUrl)
        res.cookies.delete(COGNITO_COOKIE_NAMES.STATE)
        res.cookies.delete(COGNITO_COOKIE_NAMES.VERIFIER)
        res.cookies.delete(COGNITO_COOKIE_NAMES.NONCE)
        res.cookies.delete(COGNITO_COOKIE_NAMES.NEXT)
        return res
      }

      if (!storedVerifier) {
        console.error('[auth/callback] Missing PKCE verifier cookie.')
        const errUrl = new URL('/login?error=missing_pkce_verifier', baseOrigin)
        const res = NextResponse.redirect(errUrl)
        res.cookies.delete(COGNITO_COOKIE_NAMES.STATE)
        res.cookies.delete(COGNITO_COOKIE_NAMES.VERIFIER)
        res.cookies.delete(COGNITO_COOKIE_NAMES.NONCE)
        res.cookies.delete(COGNITO_COOKIE_NAMES.NEXT)
        return res
      }

      // Compute canonical redirect URI that was registered with Cognito
      const redirectUri = `${baseOrigin}/auth/callback`

      try {
        const tokens = await exchangeCodeForTokens({
          code,
          redirectUri,
          codeVerifier: storedVerifier,
        })

        // Decode ID token claims (sub, email, name, identities)
        const claims = decodeIdTokenClaims(tokens.id_token)
        const userId = claims?.sub || ''
        const userEmail = claims?.email || ''
        const userName = claims?.name || ''

        // Synchronize authenticated user with backend RDS via /auth/session
        try {
          const backendUrl = getInternalBackendUrl()
          await fetch(`${backendUrl}/auth/session`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${tokens.access_token}`,
            },
            body: JSON.stringify({ access_token: tokens.access_token }),
            cache: 'no-store',
          })
        } catch (syncErr) {
          console.warn('[auth/callback] Backend RDS synchronization notice:', syncErr)
        }

        // Establish secure session with HttpOnly cookies
        const response = NextResponse.redirect(new URL(safeNext, baseOrigin))

        const cookieOptions = {
          httpOnly: true,
          secure: isSecure,
          sameSite: 'lax' as const,
          path: '/',
        }

        response.cookies.set(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, tokens.access_token, {
          ...cookieOptions,
          maxAge: tokens.expires_in || 3600,
        })

        if (tokens.refresh_token) {
          response.cookies.set(COGNITO_COOKIE_NAMES.REFRESH_TOKEN, tokens.refresh_token, {
            ...cookieOptions,
            maxAge: 30 * 24 * 60 * 60, // 30 days
          })
        }

        if (tokens.id_token) {
          response.cookies.set(COGNITO_COOKIE_NAMES.ID_TOKEN, tokens.id_token, {
            ...cookieOptions,
            maxAge: tokens.expires_in || 3600,
          })
        }

        // Clear temporary OAuth cookies
        response.cookies.delete(COGNITO_COOKIE_NAMES.STATE)
        response.cookies.delete(COGNITO_COOKIE_NAMES.VERIFIER)
        response.cookies.delete(COGNITO_COOKIE_NAMES.NONCE)
        response.cookies.delete(COGNITO_COOKIE_NAMES.NEXT)

        return response
      } catch (exchangeErr: any) {
        console.error('[auth/callback] Token exchange error:', exchangeErr)
        const errorDesc = exchangeErr.message || 'Token exchange failed.'
        const errUrl = new URL(`/login?error=${encodeURIComponent(errorDesc)}`, baseOrigin)
        const res = NextResponse.redirect(errUrl)
        res.cookies.delete(COGNITO_COOKIE_NAMES.STATE)
        res.cookies.delete(COGNITO_COOKIE_NAMES.VERIFIER)
        res.cookies.delete(COGNITO_COOKIE_NAMES.NONCE)
        res.cookies.delete(COGNITO_COOKIE_NAMES.NEXT)
        return res
      }
    }

    // ── Supabase Fallback Flow (for legacy OTP or code verification) ─────────
    if (code || (token_hash && type)) {
      if (CONFIG.SUPABASE_URL && CONFIG.SUPABASE_ANON_KEY) {
        const redirectTarget = new URL(safeNext, baseOrigin)
        const response = NextResponse.redirect(redirectTarget)

        const supabase = createServerClient(
          CONFIG.SUPABASE_URL,
          CONFIG.SUPABASE_ANON_KEY,
          {
            cookies: {
              getAll() {
                return cookieStore.getAll()
              },
              setAll(cookiesToSet) {
                cookiesToSet.forEach(({ name, value, options }) => {
                  try {
                    cookieStore.set(name, value, options)
                  } catch (_) {}
                  try {
                    response.cookies.set(name, value, options)
                  } catch (_) {}
                })
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
          return NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(error.message)}`, baseOrigin))
        } else if (code) {
          const { data, error } = await supabase.auth.exchangeCodeForSession(code)
          if (!error && data?.session) {
            // Also call backend /auth/session to ensure RDS sync
            try {
              const backendUrl = getInternalBackendUrl()
              await fetch(`${backendUrl}/auth/session`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  Authorization: `Bearer ${data.session.access_token}`,
                },
                body: JSON.stringify({ access_token: data.session.access_token }),
                cache: 'no-store',
              })
            } catch (_) {}
            return response
          }
          console.error('Auth callback Supabase code exchange error:', error?.message)
          return NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(error?.message || 'Exchange failed')}`, baseOrigin))
        }
      }
    }

    // Default error redirect
    const url = new URL('/login?error=auth-code-error', baseOrigin)
    return NextResponse.redirect(url)
  } catch (err: any) {
    console.error('Auth callback top-level unexpected error:', err)
    return NextResponse.redirect(new URL('/login?error=auth-code-error', baseOrigin))
  }
}
