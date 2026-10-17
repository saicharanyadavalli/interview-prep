'use server'

import { createClient } from '@/utils/supabase/server'
import { getAuthRedirectUrl } from '@/utils/auth-redirect'
import { headers } from 'next/headers'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'

function getInternalBackendUrl(): string {
  const envUrl = process.env.BACKEND_INTERNAL_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  if (envUrl && envUrl.startsWith('http')) {
    return envUrl.replace(/\/api\/backend\/?$/, '');
  }
  return 'http://127.0.0.1:8000';
}

export async function login(formData: FormData) {
  const rawIdentifier = (formData.get('identifier') || formData.get('email')) as string
  const password = formData.get('password') as string

  if (!rawIdentifier || !password) {
    return { error: 'Email or username, and password are required' }
  }

  const supabase = await createClient()
  const cleanIdentifier = rawIdentifier.trim()

  if (!cleanIdentifier.includes('@')) {
    // Input is a username — authenticate securely via backend without public email disclosure
    try {
      const backendUrl = getInternalBackendUrl()
      const res = await fetch(`${backendUrl}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: cleanIdentifier.toLowerCase(), password }),
        cache: 'no-store',
      })
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}))
        return { error: errorData.detail || 'Invalid username or password.' }
      }
      const data = await res.json()
      if (data.access_token && data.refresh_token) {
        const { error: sessionError } = await supabase.auth.setSession({
          access_token: data.access_token,
          refresh_token: data.refresh_token,
        })
        if (sessionError) {
          return { error: sessionError.message }
        }
        return { success: true }
      }
      return { error: 'Failed to establish authenticated session.' }
    } catch (err: any) {
      return { error: 'Authentication service temporarily unavailable. Please try again.' }
    }
  }

  // Direct email authentication via Supabase client
  const { data, error } = await supabase.auth.signInWithPassword({
    email: cleanIdentifier,
    password,
  })

  if (error) {
    return { error: error.message }
  }
  
  if (data?.session) {
    // Session is automatically set in HttpOnly cookies by createClient()
    return { success: true }
  }

  return { error: 'Unknown error occurred' }
}

export async function signup(formData: FormData) {
  const email = formData.get('email') as string
  const password = formData.get('password') as string
  const fullName = formData.get('fullName') as string
  const username = formData.get('username') as string

  if (!email || !password || !fullName || !username) {
    return { error: 'All fields are required' }
  }

  // Dynamically resolve request host headers for seamless fallback to /auth/callback
  const headerList = await headers()
  const host = headerList.get('x-forwarded-host') || headerList.get('host')
  const proto = headerList.get('x-forwarded-proto') || 'http'
  const requestOrigin = host ? `${proto}://${host}` : undefined

  // Ensure redirect URL points to /auth/callback on the canonical AWS deployment (preserving post-login route)
  const emailRedirectTo = getAuthRedirectUrl({
    fallbackOrigin: requestOrigin,
    preserveParams: true,
    next: '/dashboard',
  })

  const cleanEmail = email.trim().toLowerCase()
  const cleanUsername = username.trim().toLowerCase()

  const supabase = await createClient()

  // First check if username exists in RDS (fail closed if check fails)
  try {
    const backendUrl = getInternalBackendUrl()
    const checkRes = await fetch(`${backendUrl}/auth/check-username?username=${encodeURIComponent(cleanUsername)}`, {
      cache: 'no-store',
    })
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


  const { data, error } = await supabase.auth.signUp({
    email: cleanEmail,
    password,
    options: {
      emailRedirectTo,
      data: {
        full_name: fullName.trim(),
        username: cleanUsername,
      }
    }
  })

  if (error) {
    if (error.message.toLowerCase().includes("already registered") || error.message.toLowerCase().includes("already exists")) {
      return { error: `An account with email "${email}" already exists. Please sign in instead.` };
    }
    return { error: error.message }
  }

  if (data.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
    return { error: `An account with email "${email}" already exists. Please sign in instead.` };
  }
  
  // Try logging in (auto sign-in if email confirmation is disabled)
  const { error: signInError } = await supabase.auth.signInWithPassword({
    email: cleanEmail,
    password,
  })

  if (signInError) {
    if (signInError.message.toLowerCase().includes("confirm")) {
      return {
        success: true,
        message: "Signup successful! Please check your email to confirm your account before logging in."
      }
    }
    return { error: signInError.message }
  }

  return { success: true }
}

export async function logout() {
  const supabase = await createClient()
  await supabase.auth.signOut()
  return { success: true }
}
