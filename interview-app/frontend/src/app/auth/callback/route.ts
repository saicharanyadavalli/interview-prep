import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { createServerClient, type CookieOptions } from '@supabase/ssr'
import { CONFIG } from '@/lib/config'

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get('code')
  const next = searchParams.get('next') ?? '/dashboard'

  if (code) {
    if (!CONFIG.SUPABASE_URL || !CONFIG.SUPABASE_ANON_KEY) {
      console.error("Auth callback error: Supabase environment variables missing.")
      const url = new URL('/login?error=env-missing', request.url)
      return NextResponse.redirect(url)
    }
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
              cookiesToSet.forEach(({ name, value, options }) =>
                cookieStore.set(name, value, options)
              )
            } catch (error) {
              // Ignore if called from a context where cookies cannot be set
            }
          },
        },
      }
    )
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) {
      const url = new URL(next, request.url)
      return NextResponse.redirect(url)
    } else {
      console.error("Auth callback error:", error.message)
    }
  }

  const url = new URL('/login?error=auth-code-error', request.url)
  return NextResponse.redirect(url)
}
