import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import {
  COGNITO_COOKIE_NAMES,
  exchangeCodeForTokens,
  verifyCognitoIdToken,
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

function clearTemporaryCookies(response: NextResponse) {
  response.cookies.delete(COGNITO_COOKIE_NAMES.STATE)
  response.cookies.delete(COGNITO_COOKIE_NAMES.VERIFIER)
  response.cookies.delete(COGNITO_COOKIE_NAMES.NONCE)
  response.cookies.delete(COGNITO_COOKIE_NAMES.NEXT)
}

function createErrorRedirect(baseOrigin: string, errorCode: string): NextResponse {
  const redirectUrl = new URL(`/login?error=${encodeURIComponent(errorCode)}`, baseOrigin)
  const res = NextResponse.redirect(redirectUrl)
  clearTemporaryCookies(res)
  return res
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

    // 1. Handle OAuth error passed by identity provider / Cognito
    if (errorParam || errorDescription) {
      const errMessage = errorDescription || errorParam || 'OAuth authentication failed.'
      console.error('[auth/callback] Provider error:', errMessage)
      return createErrorRedirect(baseOrigin, errMessage)
    }

    // Determine target redirect destination
    const rawNext = rawNextQuery || cookieStore.get(COGNITO_COOKIE_NAMES.NEXT)?.value || '/dashboard'
    const safeNext = validateRedirectDestination(rawNext, allowedOrigins)

    const isSecure = baseOrigin.startsWith('https:')

    // 2. Read stored OAuth PKCE cookies
    const storedState = cookieStore.get(COGNITO_COOKIE_NAMES.STATE)?.value
    const storedVerifier = cookieStore.get(COGNITO_COOKIE_NAMES.VERIFIER)?.value
    const storedNonce = cookieStore.get(COGNITO_COOKIE_NAMES.NONCE)?.value

    // If code is missing, terminal error exit
    if (!code) {
      return createErrorRedirect(baseOrigin, 'auth-code-error')
    }

    // 3. Verify state cookie
    if (!storedState || !state || storedState !== state) {
      console.error('[auth/callback] State validation failed. Possible CSRF attack or expired session.')
      return createErrorRedirect(baseOrigin, 'invalid_state')
    }

    // 4. Read stored PKCE verifier cookie
    if (!storedVerifier) {
      console.error('[auth/callback] Missing PKCE verifier cookie.')
      return createErrorRedirect(baseOrigin, 'missing_pkce_verifier')
    }

    // Compute canonical redirect URI that was registered with Cognito
    const redirectUri = `${baseOrigin}/auth/callback`

    // 5. Exchange code for tokens at /oauth2/token
    let tokens
    try {
      tokens = await exchangeCodeForTokens({
        code,
        redirectUri,
        codeVerifier: storedVerifier,
      })
    } catch (exchangeErr: any) {
      console.error('[auth/callback] Token exchange error:', exchangeErr)
      const errorDesc = exchangeErr.message || 'Token exchange failed.'
      return createErrorRedirect(baseOrigin, errorDesc)
    }

    // 6. Cryptographically verify the ID token (issuer, audience/client_id, expiration, nonce)
    try {
      await verifyCognitoIdToken({
        idToken: tokens.id_token,
        expectedNonce: storedNonce,
      })
    } catch (tokenVerifyErr: any) {
      console.error('[auth/callback] ID token verification error:', tokenVerifyErr)
      const errorDesc = tokenVerifyErr.message || 'ID token verification failed.'
      return createErrorRedirect(baseOrigin, errorDesc)
    }

    // 7. Synchronize with backend RDS via /auth/session
    // If /auth/session fails, DO NOT establish an authenticated session! Clean up temporary cookies and redirect to /login?error=sync_failed.
    try {
      const backendUrl = getInternalBackendUrl()
      const syncRes = await fetch(`${backendUrl}/auth/session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens.access_token}`,
        },
        body: JSON.stringify({ access_token: tokens.access_token }),
        cache: 'no-store',
      })

      if (!syncRes.ok) {
        console.error(`[auth/callback] Backend RDS synchronization failed with status ${syncRes.status}`)
        return createErrorRedirect(baseOrigin, 'sync_failed')
      }
    } catch (syncErr: any) {
      console.error('[auth/callback] Backend RDS synchronization network error:', syncErr)
      return createErrorRedirect(baseOrigin, 'sync_failed')
    }

    // 8. Establish secure session with HttpOnly cookies
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

    // Delete temporary cookies on successful authentication
    clearTemporaryCookies(response)

    return response
  } catch (err: any) {
    console.error('Auth callback top-level unexpected error:', err)
    return createErrorRedirect(baseOrigin, 'auth-code-error')
  }
}
