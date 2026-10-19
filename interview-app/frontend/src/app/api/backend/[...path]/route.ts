import type { CognitoRefreshResponse } from '@/lib/cognito'

export const dynamic = 'force-dynamic'

export const COGNITO_COOKIE_NAMES = {
  STATE: 'cognito_oauth_state',
  VERIFIER: 'cognito_pkce_verifier',
  NONCE: 'cognito_nonce',
  NEXT: 'cognito_oauth_next',
  ACCESS_TOKEN: 'cognito_access_token',
  REFRESH_TOKEN: 'cognito_refresh_token',
  ID_TOKEN: 'cognito_id_token',
} as const

const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
  'host',
  'content-length',
])

function getInternalBackendUrl(): string {
  const envUrl = process.env.BACKEND_INTERNAL_URL || process.env.NEXT_PUBLIC_API_BASE_URL
  if (envUrl && envUrl.startsWith('http')) {
    return envUrl.replace(/\/api\/backend\/?$/, '').replace(/\/+$/, '')
  }
  return 'http://127.0.0.1:8000'
}

type RouteContext = {
  params: Promise<{ path: string[] }> | { path: string[] }
}

function getCookieFromHeader(request: Request, name: string): string | null {
  const cookieHeader = request.headers.get('cookie')
  if (!cookieHeader) return null
  const cookies = cookieHeader.split(';')
  for (const c of cookies) {
    const trimmed = c.trim()
    if (trimmed.startsWith(`${name}=`)) {
      const rawValue = trimmed.slice(name.length + 1)
      try {
        return decodeURIComponent(rawValue)
      } catch (_) {
        return rawValue
      }
    }
  }
  return null
}

async function resolveCookie(request: Request, name: string): Promise<string | null> {
  const fromHeader = getCookieFromHeader(request, name)
  if (fromHeader) return fromHeader

  // Fallback to Next.js cookie store if available
  try {
    const nextHeaders = await import('next/headers').catch(() => null)
    if (nextHeaders && typeof nextHeaders.cookies === 'function') {
      const cookieStore = await nextHeaders.cookies()
      const val = cookieStore.get(name)?.value
      if (val) return val
    }
  } catch (_) {}

  return null
}

async function resolveAccessToken(request: Request): Promise<string | null> {
  return resolveCookie(request, COGNITO_COOKIE_NAMES.ACCESS_TOKEN)
}

async function resolveRefreshToken(request: Request): Promise<string | null> {
  return resolveCookie(request, COGNITO_COOKIE_NAMES.REFRESH_TOKEN)
}

function getJwtExp(token: string): number | null {
  if (!token || typeof token !== 'string') return null
  try {
    const parts = token.split('.')
    if (parts.length < 2) return null
    const payload = parts[1]
    let base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    while (base64.length % 4 !== 0) {
      base64 += '='
    }
    const jsonString =
      typeof Buffer !== 'undefined'
        ? Buffer.from(base64, 'base64').toString('utf-8')
        : atob(base64)
    const parsed = JSON.parse(jsonString)
    if (parsed && typeof parsed.exp === 'number') {
      return parsed.exp
    }
  } catch (_) {}
  return null
}

function isTokenExpiredOrExpiring(token: string | null, thresholdSeconds: number = 30): boolean {
  if (!token) return true
  const exp = getJwtExp(token)
  if (exp === null) {
    // If it contains dots, it was intended as a JWT but exp is missing/invalid -> expired
    if (token.includes('.')) {
      return true
    }
    // Test tokens or opaque tokens without dots
    return false
  }
  const now = Math.floor(Date.now() / 1000)
  return exp - thresholdSeconds <= now
}

async function callRefreshCognitoTokens(refreshToken: string): Promise<CognitoRefreshResponse> {
  let fn: typeof import('@/lib/cognito').refreshCognitoTokens | undefined
  try {
    const mod = await import('@/lib/cognito')
    fn = mod.refreshCognitoTokens
  } catch (_) {
    // Fallback for isolated Node test runner where tsconfig path aliases are not natively resolved
    const fallbackPath = '../../../../lib/cognito.ts'
    const mod: any = await import(/* webpackIgnore: true */ fallbackPath)
    fn = mod.refreshCognitoTokens
  }
  if (!fn) {
    throw new Error('Unable to resolve refreshCognitoTokens from @/lib/cognito')
  }
  return fn({ refreshToken })
}

function isSecureRequest(request: Request): boolean {
  try {
    const url = new URL(request.url)
    if (url.protocol === 'https:') return true
  } catch (_) {}
  const proto = request.headers.get('x-forwarded-proto')
  return proto === 'https'
}

function serializeSetCookie(
  name: string,
  value: string,
  options: {
    maxAge?: number
    secure?: boolean
    path?: string
    httpOnly?: boolean
    sameSite?: 'lax' | 'strict' | 'none'
  } = {}
): string {
  const parts: string[] = [`${name}=${encodeURIComponent(value)}`]
  const path = options.path ?? '/'
  parts.push(`Path=${path}`)

  if (typeof options.maxAge === 'number') {
    parts.push(`Max-Age=${Math.floor(options.maxAge)}`)
  }

  if (options.httpOnly !== false) {
    parts.push('HttpOnly')
  }

  if (options.secure) {
    parts.push('Secure')
  }

  const sameSite = options.sameSite ?? 'lax'
  parts.push(`SameSite=${sameSite.charAt(0).toUpperCase() + sameSite.slice(1)}`)

  return parts.join('; ')
}

function serializeClearCookie(
  name: string,
  options: { secure?: boolean; path?: string } = {}
): string {
  return `${name}=; Path=${options.path ?? '/'}; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax${options.secure ? '; Secure' : ''}`
}

async function handleProxy(request: Request, context: RouteContext): Promise<Response> {
  const resolvedParams = await Promise.resolve(context.params)
  const pathSegments = resolvedParams?.path || []
  const targetPath = '/' + pathSegments.join('/')

  const incomingUrl = new URL(request.url)
  const search = incomingUrl.search
  const backendBase = getInternalBackendUrl()
  const targetUrl = `${backendBase}${targetPath}${search}`

  const forwardedHeaders = new Headers()

  // Copy allowable request headers, stripping unauthenticated or hop-by-hop authorization headers
  request.headers.forEach((value, key) => {
    const lower = key.toLowerCase()
    if (!HOP_BY_HOP_HEADERS.has(lower) && lower !== 'authorization') {
      forwardedHeaders.set(key, value)
    }
  })

  // Token Resolution & In-flight Proactive Refresh
  const accessToken = await resolveAccessToken(request)
  const refreshToken = await resolveRefreshToken(request)

  let tokenToForward: string | null = accessToken
  const cookiesToSet: string[] = []
  let cookiesToClear: string[] = []
  const isSecure = isSecureRequest(request)

  if (isTokenExpiredOrExpiring(accessToken) && refreshToken) {
    try {
      const refreshed = await callRefreshCognitoTokens(refreshToken)
      if (refreshed && refreshed.access_token) {
        tokenToForward = refreshed.access_token

        const cookieOptions = {
          secure: isSecure,
          httpOnly: true,
          sameSite: 'lax' as const,
          path: '/',
        }

        cookiesToSet.push(
          serializeSetCookie(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, refreshed.access_token, {
            ...cookieOptions,
            maxAge: refreshed.expires_in || 3600,
          })
        )

        if (refreshed.id_token) {
          cookiesToSet.push(
            serializeSetCookie(COGNITO_COOKIE_NAMES.ID_TOKEN, refreshed.id_token, {
              ...cookieOptions,
              maxAge: refreshed.expires_in || 3600,
            })
          )
        }

        if ((refreshed as any).refresh_token) {
          cookiesToSet.push(
            serializeSetCookie(COGNITO_COOKIE_NAMES.REFRESH_TOKEN, (refreshed as any).refresh_token, {
              ...cookieOptions,
              maxAge: 30 * 24 * 60 * 60,
            })
          )
        }
      } else {
        throw new Error('Refresh response missing access_token')
      }
    } catch (refreshErr) {
      console.error('[BFF Proxy] In-flight token refresh failed. Proceeding unauthenticated:', refreshErr)
      tokenToForward = null
      cookiesToClear = [
        serializeClearCookie(COGNITO_COOKIE_NAMES.ACCESS_TOKEN, { secure: isSecure }),
        serializeClearCookie(COGNITO_COOKIE_NAMES.REFRESH_TOKEN, { secure: isSecure }),
        serializeClearCookie(COGNITO_COOKIE_NAMES.ID_TOKEN, { secure: isSecure }),
      ]
    }
  }

  // Forward ONLY validated cognito_access_token as Authorization: Bearer <token>
  if (tokenToForward) {
    forwardedHeaders.set('Authorization', `Bearer ${tokenToForward}`)
  }

  // Read request body for non-GET/HEAD methods (supports JSON, multipart form data, etc.)
  let bodyBuffer: ArrayBuffer | undefined = undefined
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    try {
      const arr = await request.arrayBuffer()
      if (arr && arr.byteLength > 0) {
        bodyBuffer = arr
      }
    } catch (_) {}
  }

  try {
    const backendRes = await fetch(targetUrl, {
      method: request.method,
      headers: forwardedHeaders,
      body: bodyBuffer,
      cache: 'no-store',
    })

    const responseHeaders = new Headers()
    backendRes.headers.forEach((value, key) => {
      const lower = key.toLowerCase()
      if (!HOP_BY_HOP_HEADERS.has(lower) && lower !== 'content-encoding') {
        if (lower === 'set-cookie') {
          responseHeaders.append(key, value)
        } else {
          responseHeaders.set(key, value)
        }
      }
    })

    // Attach updated session cookies or clear cookies if refreshed/expired
    for (const c of cookiesToSet) {
      responseHeaders.append('set-cookie', c)
    }
    for (const c of cookiesToClear) {
      responseHeaders.append('set-cookie', c)
    }

    const responseBody =
      request.method === 'HEAD' || backendRes.status === 204 || backendRes.status === 304
        ? null
        : backendRes.body

    // Return backend response stream with authoritative status code
    return new Response(responseBody, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers: responseHeaders,
    })
  } catch (err: any) {
    console.error(`[BFF Proxy] Error forwarding request to backend (${targetUrl}):`, err)
    const errHeaders = new Headers()
    for (const c of cookiesToSet) {
      errHeaders.append('set-cookie', c)
    }
    for (const c of cookiesToClear) {
      errHeaders.append('set-cookie', c)
    }
    return Response.json(
      { detail: 'Backend service temporarily unavailable. Please try again shortly.' },
      { status: 503, headers: errHeaders }
    )
  }
}

export async function GET(request: Request, context: RouteContext) {
  return handleProxy(request, context)
}

export async function POST(request: Request, context: RouteContext) {
  return handleProxy(request, context)
}

export async function PUT(request: Request, context: RouteContext) {
  return handleProxy(request, context)
}

export async function DELETE(request: Request, context: RouteContext) {
  return handleProxy(request, context)
}

export async function PATCH(request: Request, context: RouteContext) {
  return handleProxy(request, context)
}

export async function HEAD(request: Request, context: RouteContext) {
  return handleProxy(request, context)
}

export async function OPTIONS(request: Request, context: RouteContext) {
  return handleProxy(request, context)
}
