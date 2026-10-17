/**
 * Authentication Redirect Utilities
 *
 * Handles validation and construction of deployment-specific redirect URLs
 * for Supabase Authentication (email confirmation, magic links, OAuth callbacks).
 *
 * Prevents cross-deployment redirect bleed (e.g. EC2 falling back to Vercel Site URL)
 * and guards against open-redirect vulnerabilities.
 */

export interface AuthRedirectValidationResult {
  isValid: boolean;
  error: string | null;
  url: string | null;
  origin: string | null;
}

/**
 * Validates that the provided redirect URL is an absolute, well-formed HTTP/HTTPS URL.
 */
export function validateAuthRedirectUrl(
  rawUrl?: string | null
): AuthRedirectValidationResult {
  if (!rawUrl || typeof rawUrl !== 'string' || !rawUrl.trim()) {
    return {
      isValid: false,
      error:
        'AUTH_REDIRECT_URL is not configured. An explicit, absolute redirect URL (e.g. http://16.113.92.222/auth/callback) is recommended.',
      url: null,
      origin: null,
    };
  }

  const trimmed = rawUrl.trim();

  try {
    const parsed = new URL(trimmed);

    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return {
        isValid: false,
        error: `AUTH_REDIRECT_URL must use http or https protocol (received: ${parsed.protocol}).`,
        url: null,
        origin: null,
      };
    }

    if (!parsed.hostname) {
      return {
        isValid: false,
        error: 'AUTH_REDIRECT_URL must include a valid hostname.',
        url: null,
        origin: null,
      };
    }

    return {
      isValid: true,
      error: null,
      url: parsed.toString(),
      origin: parsed.origin,
    };
  } catch {
    return {
      isValid: false,
      error: `AUTH_REDIRECT_URL "${trimmed}" is not a valid absolute URL.`,
      url: null,
      origin: null,
    };
  }
}

export const CANONICAL_AWS_ORIGIN = 'http://16.113.92.222';
export const CANONICAL_AWS_CALLBACK = `${CANONICAL_AWS_ORIGIN}/auth/callback`;

/**
 * Known default allowed origins for the application deployments.
 */
export const DEFAULT_ALLOWED_ORIGINS = [
  CANONICAL_AWS_ORIGIN,
  'https://interview-prep-saicharanyadavallis-projects.vercel.app',
  'http://localhost:3000',
  'http://127.0.0.1:3000',
];

export interface GetAuthRedirectUrlOptions {
  fallbackOrigin?: string | null;
  preserveParams?: boolean;
}

/**
 * Returns the configured authentication redirect URL for Supabase Auth flows
 * (e.g. emailRedirectTo during signup, OAuth redirectTo).
 *
 * Guarantees a validated redirect URL pointing to /auth/callback.
 *
 * Priority order:
 * 1. Explicit AUTH_REDIRECT_URL or NEXT_PUBLIC_AUTH_REDIRECT_URL from environment
 * 2. FRONTEND_URL or NEXT_PUBLIC_APP_URL from environment
 * 3. Request-derived fallbackOrigin (e.g. window.location.origin or Host header)
 *    ONLY IF the origin is in the allowed origins list!
 * 4. Vercel deployment URL ONLY when running in an active Vercel environment (VERCEL === '1')
 * 5. Canonical EC2 fallback: http://16.113.92.222/auth/callback
 */
export function getAuthRedirectUrl(
  optionsOrFallbackOrigin?: string | null | GetAuthRedirectUrlOptions
): string {
  let fallbackOrigin: string | null = null;
  let preserveParams = false;

  if (typeof optionsOrFallbackOrigin === 'string') {
    fallbackOrigin = optionsOrFallbackOrigin;
  } else if (optionsOrFallbackOrigin && typeof optionsOrFallbackOrigin === 'object') {
    fallbackOrigin = optionsOrFallbackOrigin.fallbackOrigin || null;
    preserveParams = Boolean(optionsOrFallbackOrigin.preserveParams);
  }

  // 1. Try explicit AUTH_REDIRECT_URL or NEXT_PUBLIC_AUTH_REDIRECT_URL from environment
  const envUrl = process.env.AUTH_REDIRECT_URL || process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL;
  if (envUrl && typeof envUrl === 'string' && envUrl.trim()) {
    try {
      const parsed = new URL(envUrl.trim());
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        if (preserveParams && (parsed.search || parsed.hash)) {
          return `${parsed.origin}/auth/callback${parsed.search}${parsed.hash}`;
        }
        return `${parsed.origin}/auth/callback`;
      }
    } catch (_) {}
  }

  // 2. Try standard deployment environment variables (FRONTEND_URL / NEXT_PUBLIC_APP_URL)
  const hostUrl = process.env.FRONTEND_URL || process.env.NEXT_PUBLIC_APP_URL;
  if (hostUrl && typeof hostUrl === 'string' && hostUrl.trim()) {
    try {
      const parsed = new URL(hostUrl.trim());
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return `${parsed.origin}/auth/callback`;
      }
    } catch (_) {}
  }

  // 3. Try request-derived fallback origin, strictly validated against allowed origins
  if (fallbackOrigin && typeof fallbackOrigin === 'string' && fallbackOrigin.trim()) {
    let candidateOrigin: string | null = null;
    try {
      const parsed = new URL(fallbackOrigin.trim());
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        candidateOrigin = parsed.origin;
      }
    } catch (_) {
      try {
        const parsed = new URL(`http://${fallbackOrigin.trim()}`);
        candidateOrigin = parsed.origin;
      } catch (_) {}
    }

    if (candidateOrigin) {
      const allowed = getAllowedOrigins();
      const isAllowed = allowed.some(
        (o) => o.toLowerCase() === candidateOrigin!.toLowerCase()
      );
      if (isAllowed) {
        return `${candidateOrigin}/auth/callback`;
      }
    }
  }

  // 4. Try Vercel environment URL ONLY if explicitly running in a Vercel deployment
  const isVercelRuntime =
    process.env.VERCEL === '1' ||
    process.env.NEXT_PUBLIC_VERCEL_ENV !== undefined;
  if (isVercelRuntime && process.env.VERCEL_URL) {
    const rawVercel = process.env.VERCEL_URL.trim();
    const vercelHost = rawVercel.startsWith('http')
      ? rawVercel
      : `https://${rawVercel}`;
    try {
      const parsed = new URL(vercelHost);
      return `${parsed.origin}/auth/callback`;
    } catch (_) {}
  }

  // 5. Canonical fallback for AWS EC2
  return CANONICAL_AWS_CALLBACK;
}

/**
 * Returns a list of trusted allowed origins, dynamically including the
 * origin of the currently configured AUTH_REDIRECT_URL.
 */
export function getAllowedOrigins(configuredUrl?: string | null): string[] {
  const origins = new Set<string>(DEFAULT_ALLOWED_ORIGINS);

  const candidates = [
    configuredUrl,
    process.env.AUTH_REDIRECT_URL,
    process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL,
    process.env.FRONTEND_URL,
    process.env.NEXT_PUBLIC_APP_URL,
  ];

  for (const target of candidates) {
    if (target && typeof target === 'string' && target.trim()) {
      try {
        const parsed = new URL(target.trim());
        if (parsed.origin && parsed.origin !== 'null') {
          origins.add(parsed.origin);
        }
      } catch (_) {}
    }
  }

  return Array.from(origins);
}

/**
 * Sanitizes and validates a redirect destination to prevent open-redirect vulnerabilities.
 *
 * Only allows:
 * 1. Safe relative paths (e.g. /dashboard, /practice?id=123)
 * 2. Absolute URLs whose origin matches one of the explicitly allowed deployment origins.
 *
 * Falls back to /dashboard for any invalid, external, or malformed input.
 */
export function validateRedirectDestination(
  destination: string | null | undefined,
  allowedOrigins: string[] = DEFAULT_ALLOWED_ORIGINS
): string {
  if (!destination || typeof destination !== 'string') {
    return '/dashboard';
  }

  const trimmed = destination.trim();
  if (!trimmed) {
    return '/dashboard';
  }

  // Reject backslashes (e.g. \evil.com, /\evil.com) and protocol-relative URLs (//evil.com)
  if (trimmed.includes('\\') || trimmed.startsWith('//')) {
    return '/dashboard';
  }

  // Handle relative paths (e.g. /dashboard, /questions/1)
  if (trimmed.startsWith('/')) {
    try {
      const parsed = new URL(trimmed, 'http://dummy.local');
      if (parsed.origin === 'http://dummy.local' && parsed.pathname.startsWith('/')) {
        return parsed.pathname + parsed.search + parsed.hash;
      }
    } catch (_) {}
    return '/dashboard';
  }

  // Handle absolute URLs (e.g. http://16.113.92.222/dashboard)
  try {
    const parsed = new URL(trimmed);
    const origins = new Set(allowedOrigins.map((o) => o.toLowerCase()));

    if (origins.has(parsed.origin.toLowerCase())) {
      return parsed.pathname + parsed.search + parsed.hash;
    }
  } catch (_) {}

  // Untrusted destination fallback
  return '/dashboard';
}
