import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import { CONFIG } from '@/lib/config'
import {
  getAllowedOrigins,
  validateRedirectDestination,
} from '@/utils/auth-redirect'

export async function GET(request: Request) {
  const requestUrl = new URL(request.url)
  const searchParams = requestUrl.searchParams
  const code = searchParams.get('code')
  const token_hash = searchParams.get('token_hash')
  const type = searchParams.get('type')
  const rawNext = searchParams.get('next')

  // Resolve trusted allowed origins (including configured AUTH_REDIRECT_URL)
  const allowedOrigins = getAllowedOrigins(process.env.AUTH_REDIRECT_URL)

  // Validate and sanitize destination to strictly prevent open redirects (defaults to /dashboard)
  const safeNext = validateRedirectDestination(rawNext, allowedOrigins)

  // Resolve authoritative deployment origin to prevent cross-deployment or internal-proxy bleed
  let baseOrigin = requestUrl.origin
  if (process.env.AUTH_REDIRECT_URL) {
    try {
      baseOrigin = new URL(process.env.AUTH_REDIRECT_URL).origin
    } catch (_) {}
  } else {
    const forwardedHost = request.headers.get('x-forwarded-host') || request.headers.get('host')
    const forwardedProto =
      request.headers.get('x-forwarded-proto') ||
      requestUrl.protocol.replace(':', '') ||
      'http'
    if (forwardedHost) {
      baseOrigin = `${forwardedProto}://${forwardedHost}`
    }
  }

  // Handle PKCE code exchange or Email OTP verification
  if (code || (token_hash && type)) {
    if (!CONFIG.SUPABASE_URL || !CONFIG.SUPABASE_ANON_KEY) {
      console.error('Auth callback error: Supabase environment variables missing.')
      const url = new URL('/login?error=env-missing', baseOrigin)
      return NextResponse.redirect(url)
    }

    const redirectTarget = new URL(safeNext, baseOrigin)
    const response = NextResponse.redirect(redirectTarget)
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
              cookiesToSet.forEach(({ name, value, options }) => {
                cookieStore.set(name, value, options)
                response.cookies.set(name, value, options)
              })
            } catch (error) {
              // Ignore if called from a context where cookies cannot be set
            }
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
    } else if (code) {
      const { error } = await supabase.auth.exchangeCodeForSession(code)
      if (!error) {
        return response
      }
      console.error('Auth callback code exchange error:', error.message)
    }
  }

  const errorDesc = searchParams.get('error_description') || searchParams.get('error')
  const errorQuery = errorDesc ? `?error=${encodeURIComponent(errorDesc)}` : '?error=auth-code-error'
  const url = new URL(`/login${errorQuery}`, baseOrigin)
  return NextResponse.redirect(url)
}
