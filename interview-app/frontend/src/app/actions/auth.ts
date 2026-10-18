'use server'

import { cookies, headers } from 'next/headers'
import { createClient } from '@/utils/supabase/server'
import { getAuthRedirectUrl, CANONICAL_AWS_ORIGIN } from '@/utils/auth-redirect'
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
} from '@/lib/cognito'

function getInternalBackendUrl(): string {
  const envUrl = process.env.BACKEND_INTERNAL_URL || process.env.NEXT_PUBLIC_API_BASE_URL
  if (envUrl && envUrl.startsWith('http')) {
    return envUrl.replace(/\/api\/backend\/?$/, '')
  }
  return 'http://127.0.0.1:8000'
}

async function getRequestOrigin(): Promise<string> {
  const headerList = await headers()
  const host = headerList.get('x-forwarded-host') || headerList.get('host')
  const proto = headerList.get('x-forwarded-proto') || 'http'
  if (host) {
    return `${proto}://${host}`
  }
  const config = getCognitoConfig()
  return config.appOrigin || CANONICAL_AWS_ORIGIN
}

/**
 * Initiates Amazon Cognito Google OAuth by setting secure state and PKCE cookies
 * and generating the Cognito Hosted UI authorization URL.
 */
export async function initiateCognitoGoogleAuth(nextTarget: string = '/dashboard') {
  const cookieStore = await cookies()
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
 * Retrieves the current session and user from Cognito cookies or Supabase fallback.
 */
export async function getCurrentSession() {
  const cookieStore = await cookies()
  const accessToken = cookieStore.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value
  const idToken = cookieStore.get(COGNITO_COOKIE_NAMES.ID_TOKEN)?.value
  const refreshToken = cookieStore.get(COGNITO_COOKIE_NAMES.REFRESH_TOKEN)?.value

  if (accessToken || idToken) {
    const claims = idToken ? decodeIdTokenClaims(idToken) : null
    const userId = claims?.sub || 'user'
    const email = claims?.email || ''
    const name = claims?.name || ''
    const username =
      claims?.['cognito:username'] || claims?.username || (email ? email.split('@')[0] : '')

    const user = {
      id: userId,
      email,
      user_metadata: {
        name,
        full_name: name,
        username,
        avatar_url: claims?.picture || '',
        email,
      },
    }

    return {
      session: {
        access_token: accessToken || '',
        id_token: idToken,
        refresh_token: refreshToken,
        token_type: 'Bearer',
        user,
      },
      user,
    }
  }

  // Fallback: check Supabase session if configured
  try {
    const supabase = await createClient()
    const {
      data: { session },
    } = await supabase.auth.getSession()
    if (session) {
      return {
        session: {
          access_token: session.access_token,
          refresh_token: session.refresh_token,
          token_type: session.token_type || 'bearer',
          user: session.user,
        },
        user: session.user,
      }
    }
  } catch (_) {}

  return { session: null, user: null }
}

export async function login(formData: FormData) {
  const rawIdentifier = (formData.get('identifier') || formData.get('email')) as string
  const password = formData.get('password') as string

  if (!rawIdentifier || !password) {
    return { error: 'Email or username, and password are required' }
  }

  const cleanIdentifier = rawIdentifier.trim()
  const origin = await getRequestOrigin()
  const isSecure = origin.startsWith('https:')
  const cookieStore = await cookies()

  // 1. Try backend authentication proxy (/auth/login)
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
        cookieStore.set(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, data.access_token, {
          httpOnly: true,
          secure: isSecure,
          sameSite: 'lax',
          path: '/',
          maxAge: 3600,
        })
        if (data.refresh_token) {
          cookieStore.set(COGNITO_COOKIE_NAMES.REFRESH_TOKEN, data.refresh_token, {
            httpOnly: true,
            secure: isSecure,
            sameSite: 'lax',
            path: '/',
            maxAge: 30 * 24 * 60 * 60,
          })
        }

        // Also sync Supabase session if available
        try {
          const supabase = await createClient()
          await supabase.auth.setSession({
            access_token: data.access_token,
            refresh_token: data.refresh_token || '',
          })
        } catch (_) {}

        return { success: true }
      }
    } else if (!cleanIdentifier.includes('@')) {
      const errorData = await res.json().catch(() => ({}))
      return { error: errorData.detail || 'Invalid username or password.' }
    }
  } catch (_) {
    if (!cleanIdentifier.includes('@')) {
      return { error: 'Authentication service temporarily unavailable. Please try again.' }
    }
  }

  // 2. Direct email authentication via Supabase fallback
  try {
    const supabase = await createClient()
    const { data, error } = await supabase.auth.signInWithPassword({
      email: cleanIdentifier,
      password,
    })

    if (error) {
      return { error: error.message }
    }

    if (data?.session) {
      cookieStore.set(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, data.session.access_token, {
        httpOnly: true,
        secure: isSecure,
        sameSite: 'lax',
        path: '/',
        maxAge: 3600,
      })
      if (data.session.refresh_token) {
        cookieStore.set(COGNITO_COOKIE_NAMES.REFRESH_TOKEN, data.session.refresh_token, {
          httpOnly: true,
          secure: isSecure,
          sameSite: 'lax',
          path: '/',
          maxAge: 30 * 24 * 60 * 60,
        })
      }
      return { success: true }
    }
  } catch (err: any) {
    return { error: err.message || 'Authentication failed.' }
  }

  return { error: 'Unknown authentication error occurred' }
}

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

  // First check if username exists in RDS (fail closed if check fails)
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

  const origin = await getRequestOrigin()
  const emailRedirectTo = getAuthRedirectUrl({
    fallbackOrigin: origin,
    preserveParams: true,
    next: '/dashboard',
  })

  const supabase = await createClient()

  const { data, error } = await supabase.auth.signUp({
    email: cleanEmail,
    password,
    options: {
      emailRedirectTo,
      data: {
        full_name: fullName.trim(),
        username: cleanUsername,
      },
    },
  })

  if (error) {
    if (
      error.message.toLowerCase().includes('already registered') ||
      error.message.toLowerCase().includes('already exists')
    ) {
      return { error: `An account with email "${email}" already exists. Please sign in instead.` }
    }
    return { error: error.message }
  }

  if (data.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
    return { error: `An account with email "${email}" already exists. Please sign in instead.` }
  }

  // Auto sign-in if email confirmation is disabled
  const { data: signInData, error: signInError } = await supabase.auth.signInWithPassword({
    email: cleanEmail,
    password,
  })

  if (signInError) {
    if (signInError.message.toLowerCase().includes('confirm')) {
      return {
        success: true,
        message: 'Signup successful! Please check your email to confirm your account before logging in.',
      }
    }
    return { error: signInError.message }
  }

  if (signInData?.session) {
    const cookieStore = await cookies()
    const isSecure = origin.startsWith('https:')
    cookieStore.set(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, signInData.session.access_token, {
      httpOnly: true,
      secure: isSecure,
      sameSite: 'lax',
      path: '/',
      maxAge: 3600,
    })
  }

  return { success: true }
}

export async function logout() {
  const cookieStore = await cookies()

  // Clear Cognito session and OAuth cookies
  cookieStore.delete(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)
  cookieStore.delete(COGNITO_COOKIE_NAMES.REFRESH_TOKEN)
  cookieStore.delete(COGNITO_COOKIE_NAMES.ID_TOKEN)
  cookieStore.delete(COGNITO_COOKIE_NAMES.STATE)
  cookieStore.delete(COGNITO_COOKIE_NAMES.VERIFIER)
  cookieStore.delete(COGNITO_COOKIE_NAMES.NONCE)
  cookieStore.delete(COGNITO_COOKIE_NAMES.NEXT)

  // Clear legacy Supabase session if present
  try {
    const supabase = await createClient()
    await supabase.auth.signOut()
  } catch (_) {}

  const origin = await getRequestOrigin()
  const logoutUrl = buildCognitoLogoutUrl({
    logoutUri: `${origin}/login`,
  })

  return { success: true, logoutUrl }
}
