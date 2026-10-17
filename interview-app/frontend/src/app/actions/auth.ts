'use server'

import { createClient } from '@/utils/supabase/server'
import { getAuthRedirectUrl } from '@/utils/auth-redirect'
import { headers } from 'next/headers'

export async function login(formData: FormData) {
  const rawIdentifier = (formData.get('identifier') || formData.get('email')) as string
  const password = formData.get('password') as string

  if (!rawIdentifier || !password) {
    return { error: 'Email or username, and password are required' }
  }

  const supabase = await createClient()
  let emailToUse = rawIdentifier.trim()

  if (!emailToUse.includes('@')) {
    // Input is a username — resolve to email using Supabase RPC
    const cleanUsername = emailToUse.toLowerCase()
    try {
      const { data: rpcResult } = await supabase.rpc("get_email_by_username", { p_username: cleanUsername })
      const resolvedEmail = Array.isArray(rpcResult) && rpcResult.length > 0 ? rpcResult[0]?.email : (typeof rpcResult === 'string' ? rpcResult : null)
      if (!resolvedEmail) {
        return { error: `No account found with username "${rawIdentifier}". Please check your username or sign in with your email address.` }
      }
      emailToUse = resolvedEmail
    } catch (_) {
      return { error: 'Failed to look up username. Please try signing in with your email address.' }
    }
  }

  const { data, error } = await supabase.auth.signInWithPassword({
    email: emailToUse,
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
  const proto = headerList.get('x-forwarded-proto') || 'https'
  const requestOrigin = host ? `${proto}://${host}` : undefined

  const emailRedirectTo = getAuthRedirectUrl({
    fallbackOrigin: requestOrigin,
    preserveParams: true,
    next: '/dashboard',
  })

  const cleanEmail = email.trim().toLowerCase()
  const cleanUsername = username.trim().toLowerCase()

  const supabase = await createClient()

  // First check if username exists
  try {
    const { data: rpcEmail } = await supabase.rpc("get_email_by_username", { p_username: cleanUsername })
    const isTaken = Array.isArray(rpcEmail) ? rpcEmail.length > 0 : Boolean(rpcEmail)
    if (isTaken) {
      return { error: `Username "${username}" is already taken. Please choose another username.` }
    }
  } catch (_) {}

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
  
  // Try logging in
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
