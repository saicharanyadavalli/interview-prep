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

/**
 * Known default allowed origins for the application deployments.
 */
export const DEFAULT_ALLOWED_ORIGINS = [
  'http://16.113.92.222',
  'https://interview-prep-saicharanyadavallis-projects.vercel.app',
  'http://localhost:3000',
  'http://127.0.0.1:3000',
];

/**
 * Returns the configured authentication redirect URL for Supabase Auth flows
 * (e.g. emailRedirectTo during signup, OAuth redirectTo).
 *
 * Guarantees a clean, exact redirect URL pointing strictly to /auth/callback
 * (without query parameters that break Supabase Dashboard whitelist matching).
 *
 * If AUTH_REDIRECT_URL is not explicitly configured, gracefully falls back to:
 * 1. The provided fallbackOrigin (e.g. from request headers or window.location.origin)
 * 2. FRONTEND_URL or NEXT_PUBLIC_APP_URL
 * 3. Vercel deployment URL if on Vercel
 * 4. Default EC2 origin: http://16.113.92.222/auth/callback
 */
export function getAuthRedirectUrl(fallbackOrigin?: string | null): string {
  // 1. Try explicit AUTH_REDIRECT_URL from environment
  const envUrl = process.env.AUTH_REDIRECT_URL || process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL;
  if (envUrl && typeof envUrl === 'string' && envUrl.trim()) {
    try {
      const parsed = new URL(envUrl.trim());
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return `${parsed.origin}/auth/callback`;
      }
    } catch (_) {}
  }

  // 2. Try request-derived fallback origin (e.g. Host header from server actions or window.location.origin)
  if (fallbackOrigin && typeof fallbackOrigin === 'string' && fallbackOrigin.trim()) {
    try {
      const parsed = new URL(fallbackOrigin.trim());
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return `${parsed.origin}/auth/callback`;
      }
    } catch (_) {
      try {
        const parsed = new URL(`http://${fallbackOrigin.trim()}`);
        return `${parsed.origin}/auth/callback`;
      } catch (_) {}
    }
  }

  // 3. Try standard deployment environment variables
  const hostUrl = process.env.FRONTEND_URL || process.env.NEXT_PUBLIC_APP_URL;
  if (hostUrl && typeof hostUrl === 'string' && hostUrl.trim()) {
    try {
      const parsed = new URL(hostUrl.trim());
      return `${parsed.origin}/auth/callback`;
    } catch (_) {}
  }

  // 4. Try Vercel environment URL
  if (process.env.VERCEL_URL) {
    return `https://${process.env.VERCEL_URL}/auth/callback`;
  }

  // 5. Default canonical fallback for EC2
  return 'http://16.113.92.222/auth/callback';
}

/**
 * Returns a list of trusted allowed origins, dynamically including the
 * origin of the currently configured AUTH_REDIRECT_URL.
 */
export function getAllowedOrigins(configuredUrl?: string | null): string[] {
  const origins = new Set<string>(DEFAULT_ALLOWED_ORIGINS);

  const target =
    configuredUrl || process.env.AUTH_REDIRECT_URL || process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL;
  if (target) {
    try {
      const parsed = new URL(target);
      if (parsed.origin && parsed.origin !== 'null') {
        origins.add(parsed.origin);
      }
    } catch (_) {}
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
