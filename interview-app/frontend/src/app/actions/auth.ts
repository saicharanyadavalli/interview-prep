'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'

export async function login(formData: FormData) {
  const email = formData.get('email') as string
  const password = formData.get('password') as string

  if (!email || !password) {
    return { error: 'Email and password are required' }
  }

  const supabase = await createClient()
  const { data, error } = await supabase.auth.signInWithPassword({
    email,
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

  const cleanEmail = email.trim().toLowerCase()
  const cleanUsername = username.trim().toLowerCase()

  const supabase = await createClient()

  // First check if username exists
  try {
    const { data: rpcEmail } = await supabase.rpc("get_email_by_username", { p_username: cleanUsername })
    if (rpcEmail) {
      return { error: `Username "${username}" is already taken. Please choose another username.` }
    }
  } catch (_) {}

  const { data, error } = await supabase.auth.signUp({
    email: cleanEmail,
    password,
    options: {
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
  await supabase.auth.signInWithPassword({
    email: cleanEmail,
    password,
  })

  return { success: true }
}

export async function logout() {
  const supabase = await createClient()
  await supabase.auth.signOut()
  return { success: true }
}
