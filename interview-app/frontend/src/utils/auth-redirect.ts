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
        'AUTH_REDIRECT_URL environment variable is not configured. An explicit, absolute redirect URL (e.g. http://16.113.92.222/auth/callback?next=/dashboard) is required to ensure authentication callbacks do not fall back to another deployment.',
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
 * Returns the configured authentication redirect URL for Supabase Auth flows
 * (e.g. emailRedirectTo during signup).
 *
 * Normalizes the path to /auth/callback and ensures the `next` query parameter is present.
 */
export function getAuthRedirectUrl(
  intendedNext: string = '/dashboard'
): { url: string; error: null } | { url: null; error: string } {
  const envUrl = process.env.AUTH_REDIRECT_URL;
  const validation = validateAuthRedirectUrl(envUrl);

  if (!validation.isValid || !validation.url) {
    return {
      url: null,
      error: validation.error || 'Invalid AUTH_REDIRECT_URL configuration.',
    };
  }

  try {
    const parsed = new URL(validation.url);

    // Normalize path to /auth/callback if just root or base domain was supplied
    if (parsed.pathname === '/' || !parsed.pathname) {
      parsed.pathname = '/auth/callback';
    }

    // Ensure `next` query parameter exists and is safe
    if (!parsed.searchParams.has('next')) {
      const safeNext =
        intendedNext.startsWith('/') && !intendedNext.startsWith('//')
          ? intendedNext
          : '/dashboard';
      parsed.searchParams.set('next', safeNext);
    }

    return {
      url: parsed.toString(),
      error: null,
    };
  } catch (err: any) {
    return {
      url: null,
      error: err?.message || 'Failed to construct auth redirect URL.',
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
 * Returns a list of trusted allowed origins, dynamically including the
 * origin of the currently configured AUTH_REDIRECT_URL.
 */
export function getAllowedOrigins(configuredUrl?: string | null): string[] {
  const origins = new Set<string>(DEFAULT_ALLOWED_ORIGINS);

  const target = configuredUrl || process.env.AUTH_REDIRECT_URL;
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
