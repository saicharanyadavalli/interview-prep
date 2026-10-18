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
      return decodeURIComponent(trimmed.slice(name.length + 1))
    }
  }
  return null
}

async function resolveAccessToken(request: Request): Promise<string | null> {
  const fromHeader = getCookieFromHeader(request, COGNITO_COOKIE_NAMES.ACCESS_TOKEN)
  if (fromHeader) return fromHeader

  // Fallback to Next.js cookie store if available
  try {
    const nextHeaders = await import('next/headers').catch(() => null)
    if (nextHeaders && typeof nextHeaders.cookies === 'function') {
      const cookieStore = await nextHeaders.cookies()
      const val = cookieStore.get(COGNITO_COOKIE_NAMES.ACCESS_TOKEN)?.value
      if (val) return val
    }
  } catch (_) {}

  return null
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

  // Forward ONLY cognito_access_token as Authorization: Bearer <token>
  const cognitoAccessToken = await resolveAccessToken(request)
  if (cognitoAccessToken) {
    forwardedHeaders.set('Authorization', `Bearer ${cognitoAccessToken}`)
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
        responseHeaders.set(key, value)
      }
    })

    // Return backend response stream with authoritative status code
    return new Response(backendRes.body, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers: responseHeaders,
    })
  } catch (err: any) {
    console.error(`[BFF Proxy] Error forwarding request to backend (${targetUrl}):`, err)
    return Response.json(
      { detail: 'Backend service temporarily unavailable. Please try again shortly.' },
      { status: 503 }
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
