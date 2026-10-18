'use server'

import { cookies, headers } from 'next/headers'
import {
  CANONICAL_AWS_ORIGIN,
  getAllowedOrigins,
  cleanEnvValue,
} from '@/utils/auth-redirect'
import {
  COGNITO_COOKIE_NAMES,
  generateState,
  generateNonce,
  generateCodeVerifier,
  computeCodeChallenge,
  buildCognitoAuthorizeUrl,
  buildCognitoLogoutUrl,
  decodeIdTokenClaims,
  getCognitoConfig,
  refreshCognitoTokens,
  verifyIdTokenCryptographically,
  signUpWithCognito,
  confirmSignUpWithCognito,
  resendConfirmationCodeWithCognito,
  initiateUserPasswordAuth,
  forgotPasswordWithCognito,
  confirmForgotPasswordWithCognito,
} from '@/lib/cognito'

class InMemoryCookieStore {
  private cookies = new Map<string, string>()

  get(name: string) {
    const val = this.cookies.get(name)
    return val !== undefined ? { name, value: val } : undefined
  }

  set(name: string, value: string, _options?: any) {
    this.cookies.set(name, value)
    return this
  }

  delete(name: string) {
    this.cookies.delete(name)
    return this
  }

  has(name: string) {
    return this.cookies.has(name)
  }

  clear() {
    this.cookies.clear()
  }
}

let mockCookieStore: any = null
let mockHeaderStore: any = null

function __setMockCookieStore(store: any) {
  mockCookieStore = store
}

function __setMockHeaderStore(store: any) {
  mockHeaderStore = store
}

function __resetMockStores() {
  mockCookieStore = null
  mockHeaderStore = null
}

async function getCookieStore() {
  if (mockCookieStore) return mockCookieStore
  try {
    return await cookies()
  } catch (_) {
    if (!mockCookieStore) {
      mockCookieStore = new InMemoryCookieStore()
    }
    return mockCookieStore
  }
}

async function getRequestHeaders() {
  if (mockHeaderStore) return mockHeaderStore
  try {
    return await headers()
  } catch (_) {
    return {
      get: (_name: string) => null,
    }
  }
}

function getInternalBackendUrl(): string {
  const envUrl = process.env.BACKEND_INTERNAL_URL || process.env.NEXT_PUBLIC_API_BASE_URL
  if (envUrl && envUrl.startsWith('http')) {
    return envUrl.replace(/\/api\/backend\/?$/, '')
  }
  return 'http://127.0.0.1:8000'
}

async function getRequestOrigin(): Promise<string> {
  const config = getCognitoConfig()
  const cleanAppOrigin = cleanEnvValue(process.env.PUBLIC_APP_ORIGIN) || cleanEnvValue(config.appOrigin)
  const canonicalOrigin = cleanAppOrigin || CANONICAL_AWS_ORIGIN
  const allowedOrigins = getAllowedOrigins(cleanAppOrigin)

  const headerList = await getRequestHeaders()
  const host = headerList.get('x-forwarded-host') || headerList.get('host')
  const proto = headerList.get('x-forwarded-proto') || 'http'

  if (host) {
    try {
      const candidate = new URL(`${proto}://${host}`).origin
      const candidateHost = new URL(candidate).hostname

      // Permit localhost / 127.0.0.1 in development or testing
      if (candidateHost === 'localhost' || candidateHost === '127.0.0.1') {
        return candidate
      }

      // In production or staging, require HTTPS and validate candidate against allowed origins
      const isAllowed = allowedOrigins.some(
        (allowed) => allowed.toLowerCase() === candidate.toLowerCase()
      )
      if (isAllowed) {
        const isProdOrStaging =
          process.env.NODE_ENV === 'production' ||
          process.env.APP_ENV === 'staging' ||
          process.env.ENVIRONMENT === 'staging'
        if (isProdOrStaging && !candidate.startsWith('https:')) {
          // Fall back to canonical secure origin if forwarded proto is insecure in production/staging
          return canonicalOrigin.startsWith('https:') ? canonicalOrigin : `https://${new URL(canonicalOrigin).host}`
        }
        return candidate
      }
    } catch (_) {}
  }

  return canonicalOrigin
}

/**
 * Initiates Amazon Cognito Google OAuth by setting secure state and PKCE cookies
 * and generating the Cognito Hosted UI authorization URL.
 */
export async function initiateCognitoGoogleAuth(nextTarget: string = '/dashboard') {
  const cookieStore = await getCookieStore()
  const origin = await getRequestOrigin()
  const redirectUri = `${origin}/auth/callback`

  const state = generateState(32)
  const nonce = generateNonce(32)
  const codeVerifier = generateCodeVerifier(64)
  const codeChallenge = await computeCodeChallenge(codeVerifier)

  const isSecure = origin.startsWith('https:')
  const cookieOpts = {
    httpOnly: true,
    secure: isSecure,
    sameSite: 'lax' as const,
    path: '/',
    maxAge: 600, // 10 minutes TTL
  }

  cookieStore.set(COGNITO_COOKIE_NAMES.STATE, state, cookieOpts)
  cookieStore.set(COGNITO_COOKIE_NAMES.VERIFIER, codeVerifier, cookieOpts)
  cookieStore.set(COGNITO_COOKIE_NAMES.NONCE, nonce, cookieOpts)
  cookieStore.set(COGNITO_COOKIE_NAMES.NEXT, nextTarget, cookieOpts)

  const authorizeUrl = buildCognitoAuthorizeUrl({
    redirectUri,
    state,
    nonce,
    codeChallenge,
    identityProvider: 'Google',
  })

  return { url: authorizeUrl }
}

/**
 * Clears all Cognito session cookies.
 */
async function clearSessionCookies(cookieStore: any) {
  try {
    cookieStore.delete(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)
    cookieStore.delete(COGNITO_COOKIE_NAMES.ID_TOKEN)
    cookieStore.delete(COGNITO_COOKIE_NAMES.REFRESH_TOKEN)
  } catch (_) {}
}

/**
 * Retrieves the current session and user from Cognito cookies.
 * Does NOT derive session solely from unverified tokens: verifies ID token cryptographically.
 * Refreshes expired tokens via refresh token, storing and returning newly issued tokens.
 * If refresh or verification fails, clears session cookies cleanly.
 * Never exposes raw refresh tokens in returned session.
 */
export async function getCurrentSession() {
  const cookieStore = await getCookieStore()
  const accessToken = cookieStore.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value
  let idToken = cookieStore.get(COGNITO_COOKIE_NAMES.ID_TOKEN)?.value
  const refreshToken = cookieStore.get(COGNITO_COOKIE_NAMES.REFRESH_TOKEN)?.value

  if (!idToken && !accessToken) {
    return { session: null, user: null }
  }

  // Pre-inspect claims to check expiration
  let claims = idToken ? decodeIdTokenClaims(idToken) : null
  const now = Math.floor(Date.now() / 1000)
  const isExpired = Boolean(claims?.exp && claims.exp < now)

  let activeAccessToken = accessToken || ''
  let activeIdToken = idToken || ''

  // If token is expired or ID token is missing, attempt refresh if refresh token exists
  if ((isExpired || !idToken) && refreshToken) {
    try {
      const refreshed = await refreshCognitoTokens({ refreshToken })
      const origin = await getRequestOrigin()
      const isSecure = origin.startsWith('https:')
      const cookieOpts = {
        httpOnly: true,
        secure: isSecure,
        sameSite: 'lax' as const,
        path: '/',
        maxAge: refreshed.expires_in || 3600,
      }

      cookieStore.set(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, refreshed.access_token, cookieOpts)
      activeAccessToken = refreshed.access_token

      if (refreshed.id_token) {
        cookieStore.set(COGNITO_COOKIE_NAMES.ID_TOKEN, refreshed.id_token, cookieOpts)
        activeIdToken = refreshed.id_token
        idToken = refreshed.id_token
      }
    } catch (_) {
      // Refresh failed: clear session cookies cleanly to prevent stuck invalid sessions
      await clearSessionCookies(cookieStore)
      return { session: null, user: null }
    }
  } else if (isExpired && !refreshToken) {
    // Expired without refresh token: clear cookies and fail closed
    await clearSessionCookies(cookieStore)
    return { session: null, user: null }
  }

  if (!activeIdToken) {
    // Missing ID token and cannot refresh: fail closed
    await clearSessionCookies(cookieStore)
    return { session: null, user: null }
  }

  // Cryptographically verify ID token
  let verifiedClaims: any
  try {
    verifiedClaims = await verifyIdTokenCryptographically(activeIdToken)
  } catch (verifyErr) {
    // Cryptographic verification failed: clear session cookies and fail closed
    await clearSessionCookies(cookieStore)
    return { session: null, user: null }
  }

  const userId = verifiedClaims.sub || 'user'
  const email = verifiedClaims.email || ''
  const name = verifiedClaims.name || ''
  const username =
    verifiedClaims['cognito:username'] ||
    verifiedClaims.username ||
    (email ? email.split('@')[0] : '')

  const user = {
    id: userId,
    email,
    user_metadata: {
      name,
      full_name: name,
      username,
      avatar_url: verifiedClaims.picture || '',
      email,
    },
  }

  // Never expose raw refresh token in returned value
  return {
    session: {
      access_token: activeAccessToken,
      id_token: activeIdToken,
      token_type: 'Bearer',
      user,
    },
    user,
  }
}

/**
 * Authenticates user via Cognito native InitiateAuth or backend login proxy.
 * Sets secure HttpOnly cookies for access, ID, and refresh tokens.
 */
export async function login(formData: FormData) {
  const rawIdentifier = (formData.get('identifier') || formData.get('email')) as string
  const password = formData.get('password') as string

  if (!rawIdentifier || !password) {
    return { error: 'Email or username, and password are required' }
  }

  const cleanIdentifier = rawIdentifier.trim()
  const origin = await getRequestOrigin()
  const isSecure = origin.startsWith('https:')
  const cookieStore = await getCookieStore()

  const setCognitoCookies = (tokens: {
    accessToken: string
    idToken?: string
    refreshToken?: string
    expiresIn?: number
  }) => {
    cookieStore.set(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, tokens.accessToken, {
      httpOnly: true,
      secure: isSecure,
      sameSite: 'lax',
      path: '/',
      maxAge: tokens.expiresIn || 3600,
    })
    if (tokens.idToken) {
      cookieStore.set(COGNITO_COOKIE_NAMES.ID_TOKEN, tokens.idToken, {
        httpOnly: true,
        secure: isSecure,
        sameSite: 'lax',
        path: '/',
        maxAge: tokens.expiresIn || 3600,
      })
    }
    if (tokens.refreshToken) {
      cookieStore.set(COGNITO_COOKIE_NAMES.REFRESH_TOKEN, tokens.refreshToken, {
        httpOnly: true,
        secure: isSecure,
        sameSite: 'lax',
        path: '/',
        maxAge: 30 * 24 * 60 * 60,
      })
    }
  }

  // Case 1: Identifier is a username (no '@') -> resolve via backend authentication proxy
  if (!cleanIdentifier.includes('@')) {
    try {
      const backendUrl = getInternalBackendUrl()
      const res = await fetch(`${backendUrl}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: cleanIdentifier.toLowerCase(), password }),
        cache: 'no-store',
      })

      if (res.ok) {
        const data = await res.json()
        if (data.access_token) {
          setCognitoCookies({
            accessToken: data.access_token,
            idToken: data.id_token,
            refreshToken: data.refresh_token,
            expiresIn: data.expires_in,
          })
          return { success: true }
        }
      } else {
        const errorData = await res.json().catch(() => ({}))
        return { error: errorData.detail || 'Invalid username or password.' }
      }
    } catch (_) {
      return { error: 'Authentication service temporarily unavailable. Please try again.' }
    }
  }

  // Case 2: Identifier is an email -> authenticate with Cognito USER_PASSWORD_AUTH
  try {
    const authResult = await initiateUserPasswordAuth(cleanIdentifier.toLowerCase(), password)
    if (authResult.accessToken) {
      setCognitoCookies({
        accessToken: authResult.accessToken,
        idToken: authResult.idToken,
        refreshToken: authResult.refreshToken,
        expiresIn: authResult.expiresIn,
      })
      return { success: true }
    }
  } catch (cognitoErr: any) {
    const code = cognitoErr.code || ''
    if (code === 'UserNotConfirmedException') {
      return {
        error: 'User is not confirmed. Please check your email for a verification code.',
        needsConfirmation: true,
        email: cleanIdentifier.toLowerCase(),
      }
    }
    if (code === 'NotAuthorizedException' || code === 'UserNotFoundException') {
      return { error: 'Invalid email or password.' }
    }

    // Fallback: If direct Cognito endpoint returned network or configuration error, try backend proxy
    try {
      const backendUrl = getInternalBackendUrl()
      const res = await fetch(`${backendUrl}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: cleanIdentifier.toLowerCase(), password }),
        cache: 'no-store',
      })
      if (res.ok) {
        const data = await res.json()
        if (data.access_token) {
          setCognitoCookies({
            accessToken: data.access_token,
            idToken: data.id_token,
            refreshToken: data.refresh_token,
            expiresIn: data.expires_in,
          })
          return { success: true }
        }
      } else {
        const errorData = await res.json().catch(() => ({}))
        return { error: errorData.detail || 'Invalid email or password.' }
      }
    } catch (_) {}

    return { error: cognitoErr.message || 'Authentication failed.' }
  }

  return { error: 'Unknown authentication error occurred' }
}

/**
 * Registers a new user via Amazon Cognito and validates username uniqueness in RDS.
 */
export async function signup(formData: FormData) {
  const email = formData.get('email') as string
  const password = formData.get('password') as string
  const fullName = formData.get('fullName') as string
  const username = formData.get('username') as string

  if (!email || !password || !fullName || !username) {
    return { error: 'All fields are required' }
  }

  const cleanEmail = email.trim().toLowerCase()
  const cleanUsername = username.trim().toLowerCase()
  const cleanFullName = fullName.trim()

  // 1. Check if username exists in RDS (fail closed if check fails)
  try {
    const backendUrl = getInternalBackendUrl()
    const checkRes = await fetch(
      `${backendUrl}/auth/check-username?username=${encodeURIComponent(cleanUsername)}`,
      { cache: 'no-store' }
    )
    if (checkRes.ok) {
      const checkData = await checkRes.json()
      if (checkData.available === false) {
        return { error: `Username "${username}" is already taken. Please choose another username.` }
      }
    } else {
      return { error: 'Unable to verify username availability. Please try again.' }
    }
  } catch (_) {
    return { error: 'Unable to verify username availability. Please try again.' }
  }

  // 2. Register user with Cognito Identity Provider
  try {
    const result = await signUpWithCognito(cleanEmail, password, cleanUsername, cleanFullName)
    if (!result.userConfirmed) {
      return {
        success: true,
        needsConfirmation: true,
        email: cleanEmail,
        message: 'Please check your email for a verification code.',
      }
    }
    return { success: true }
  } catch (err: any) {
    const code = err.code || err.name || ''
    const msg = err.message || 'Signup failed'
    if (
      code === 'UsernameExistsException' ||
      msg.toLowerCase().includes('already exists') ||
      msg.toLowerCase().includes('already registered')
    ) {
      return { error: `An account with email "${email}" already exists. Please sign in instead.` }
    }
    return { error: msg }
  }
}

/**
 * Confirms user email registration with a 6-digit confirmation code.
 */
export async function confirmEmail(email: string, code: string) {
  if (!email || !code) {
    return { error: 'Email and verification code are required.' }
  }
  const cleanEmail = email.trim().toLowerCase()
  const cleanCode = code.trim()

  try {
    await confirmSignUpWithCognito(cleanEmail, cleanCode)
    return { success: true, message: 'Email confirmed successfully. You can now sign in.' }
  } catch (err: any) {
    const errCode = err.code || ''
    if (errCode === 'CodeMismatchException') {
      return { error: 'Invalid verification code. Please check and try again.' }
    }
    if (errCode === 'ExpiredCodeException') {
      return { error: 'Verification code has expired. Please request a new code.' }
    }
    return { error: err.message || 'Confirmation failed.' }
  }
}

/**
 * Resends user confirmation code to registered email address.
 */
export async function resendVerificationCode(email: string) {
  if (!email) {
    return { error: 'Email is required.' }
  }
  const cleanEmail = email.trim().toLowerCase()

  try {
    const result = await resendConfirmationCodeWithCognito(cleanEmail)
    return {
      success: true,
      message: 'A new verification code has been sent to your email.',
      deliveryDetails: result.codeDeliveryDetails,
    }
  } catch (err: any) {
    return { error: err.message || 'Failed to resend verification code.' }
  }
}

/**
 * Requests a password reset code for the specified email address.
 */
export async function requestPasswordReset(email: string) {
  if (!email) {
    return { error: 'Email is required.' }
  }
  const cleanEmail = email.trim().toLowerCase()

  try {
    const result = await forgotPasswordWithCognito(cleanEmail)
    return {
      success: true,
      message: 'Password reset code has been sent to your email.',
      deliveryDetails: result.codeDeliveryDetails,
    }
  } catch (err: any) {
    return { error: err.message || 'Failed to request password reset.' }
  }
}

/**
 * Confirms password reset using verification code and sets new password.
 */
export async function confirmPasswordReset(email: string, code: string, newPassword: string) {
  if (!email || !code || !newPassword) {
    return { error: 'Email, code, and new password are required.' }
  }
  const cleanEmail = email.trim().toLowerCase()
  const cleanCode = code.trim()

  try {
    await confirmForgotPasswordWithCognito(cleanEmail, cleanCode, newPassword)
    return {
      success: true,
      message: 'Password has been reset successfully. You can now sign in with your new password.',
    }
  } catch (err: any) {
    const errCode = err.code || ''
    if (errCode === 'CodeMismatchException') {
      return { error: 'Invalid verification code. Please check and try again.' }
    }
    if (errCode === 'ExpiredCodeException') {
      return { error: 'Verification code has expired. Please request a new code.' }
    }
    return { error: err.message || 'Password reset failed.' }
  }
}

/**
 * Clears all Cognito session cookies and returns Cognito Hosted UI logout URL.
 */
export async function logout() {
  const cookieStore = await getCookieStore()

  // Clear all Cognito session and OAuth cookies
  cookieStore.delete(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)
  cookieStore.delete(COGNITO_COOKIE_NAMES.REFRESH_TOKEN)
  cookieStore.delete(COGNITO_COOKIE_NAMES.ID_TOKEN)
  cookieStore.delete(COGNITO_COOKIE_NAMES.STATE)
  cookieStore.delete(COGNITO_COOKIE_NAMES.VERIFIER)
  cookieStore.delete(COGNITO_COOKIE_NAMES.NONCE)
  cookieStore.delete(COGNITO_COOKIE_NAMES.NEXT)

  const origin = await getRequestOrigin()
  const logoutUrl = buildCognitoLogoutUrl({
    logoutUri: `${origin}/login`,
  })

  return { success: true, logoutUrl }
}

// Aliases for authentication action helpers
export async function confirmSignUp(email: string, code: string) {
  return confirmEmail(email, code)
}

export async function resendConfirmationCode(email: string) {
  return resendVerificationCode(email)
}

export async function forgotPassword(email: string) {
  return requestPasswordReset(email)
}

export async function confirmForgotPassword(email: string, code: string, newPassword: string) {
  return confirmPasswordReset(email, code, newPassword)
}
