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
      console.error('[auth/callback] Provider error reported')
      return createErrorRedirect(baseOrigin, 'oauth_provider_error')
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

    // 3. Verify state cookie against state query param
    if (!storedState || !state || storedState !== state) {
      console.error('[auth/callback] State validation failed. Possible CSRF attack or expired session.')
      return createErrorRedirect(baseOrigin, 'invalid_state')
    }

    // 4. Require stored PKCE verifier cookie
    if (!storedVerifier) {
      console.error('[auth/callback] Missing PKCE verifier cookie.')
      return createErrorRedirect(baseOrigin, 'missing_pkce_verifier')
    }

    // 5. Require stored nonce cookie
    if (!storedNonce) {
      console.error('[auth/callback] Missing nonce cookie.')
      return createErrorRedirect(baseOrigin, 'missing_nonce')
    }

    // Compute canonical redirect URI that was registered with Cognito
    const redirectUri = `${baseOrigin}/auth/callback`

    // 6. Exchange code for tokens at ${COGNITO_DOMAIN}/oauth2/token using code_verifier
    let tokens
    try {
      tokens = await exchangeCodeForTokens({
        code,
        redirectUri,
        codeVerifier: storedVerifier,
      })
    } catch (_exchangeErr: any) {
      console.error('[auth/callback] Token exchange failed.')
      return createErrorRedirect(baseOrigin, 'token_exchange_failed')
    }

    if (!tokens || !tokens.access_token || !tokens.id_token) {
      console.error('[auth/callback] Token exchange response missing required tokens.')
      return createErrorRedirect(baseOrigin, 'invalid_token_response')
    }

    // 7. Cryptographically verify the ID token (signature, issuer, client_id/aud, exp, nonce, token_use === 'id')
    try {
      const verifiedClaims = await verifyCognitoIdToken({
        idToken: tokens.id_token,
        expectedNonce: storedNonce,
      })

      // Strict validation of required claims
      if (!verifiedClaims || !verifiedClaims.sub) {
        console.error('[auth/callback] ID token missing sub claim.')
        return createErrorRedirect(baseOrigin, 'invalid_id_token')
      }
      if (verifiedClaims.token_use !== 'id') {
        console.error('[auth/callback] ID token token_use claim is not "id".')
        return createErrorRedirect(baseOrigin, 'invalid_id_token')
      }
    } catch (_tokenVerifyErr: any) {
      console.error('[auth/callback] ID token verification failed.')
      return createErrorRedirect(baseOrigin, 'id_token_verification_failed')
    }

    // 8. Synchronize with backend RDS via /auth/session using verified cognito_access_token
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
    } catch (_syncErr: any) {
      console.error('[auth/callback] Backend RDS synchronization network error.')
      return createErrorRedirect(baseOrigin, 'sync_failed')
    }

    // 9. Establish secure session cookies ONLY after validation and backend identity synchronization succeed
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

    // Delete temporary cookies on both success and failure exit paths
    clearTemporaryCookies(response)

    return response
  } catch (_err: any) {
    console.error('[auth/callback] Top-level unexpected error occurred during auth callback flow.')
    return createErrorRedirect(baseOrigin, 'auth-code-error')
  }
}
