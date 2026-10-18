import { NextResponse } from 'next/server'
import {
  COGNITO_COOKIE_NAMES,
  generateState,
  generateNonce,
  generateCodeVerifier,
  computeCodeChallenge,
  buildCognitoAuthorizeUrl,
  getCognitoConfig,
} from '@/lib/cognito'
import {
  getAllowedOrigins,
  validateRedirectDestination,
  cleanEnvValue,
  CANONICAL_AWS_ORIGIN,
} from '@/utils/auth-redirect'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const requestUrl = new URL(request.url)
  const provider = requestUrl.searchParams.get('provider') || 'Google'
  const rawNext = requestUrl.searchParams.get('next') || '/dashboard'
  const config = getCognitoConfig()

  const cleanAuthRedirect = cleanEnvValue(process.env.AUTH_REDIRECT_URL)
  const allowedOrigins = getAllowedOrigins(cleanAuthRedirect)
  const safeNext = validateRedirectDestination(rawNext, allowedOrigins)

  const forwardedHost = request.headers.get('x-forwarded-host') || request.headers.get('host')
  const forwardedProto = request.headers.get('x-forwarded-proto') || 'http'
  const origin = forwardedHost
    ? `${forwardedProto}://${forwardedHost}`
    : config.appOrigin || CANONICAL_AWS_ORIGIN
  const redirectUri = `${origin}/auth/callback`

  const state = generateState(32)
  const nonce = generateNonce(32)
  const codeVerifier = generateCodeVerifier(64)
  const codeChallenge = await computeCodeChallenge(codeVerifier)

  const authorizeUrl = buildCognitoAuthorizeUrl({
    redirectUri,
    state,
    nonce,
    codeChallenge,
    identityProvider: provider,
  })

  const isSecure = origin.startsWith('https:')
  const response = NextResponse.redirect(authorizeUrl)

  const cookieOptions = {
    httpOnly: true,
    secure: isSecure,
    sameSite: 'lax' as const,
    path: '/',
    maxAge: 600,
  }

  response.cookies.set(COGNITO_COOKIE_NAMES.STATE, state, cookieOptions)
  response.cookies.set(COGNITO_COOKIE_NAMES.VERIFIER, codeVerifier, cookieOptions)
  response.cookies.set(COGNITO_COOKIE_NAMES.NONCE, nonce, cookieOptions)
  response.cookies.set(COGNITO_COOKIE_NAMES.NEXT, safeNext, cookieOptions)

  return response
}
