/**
 * Authentication Redirect Utilities (AWS EC2 Canonical)
 *
 * Handles validation and construction of deployment-specific redirect URLs
 * for Supabase Authentication (email confirmation, magic links, OAuth callbacks).
 *
 * Strictly enforces canonical AWS EC2 deployment destination (http://16.113.92.222)
 * and guards against open-redirect vulnerabilities.
 */

export interface AuthRedirectValidationResult {
  isValid: boolean;
  error: string | null;
  url: string | null;
  origin: string | null;
}

/**
 * Sanitizes an environment variable value by trimming whitespace and
 * removing surrounding single or double quotes (e.g. from Docker/env files).
 */
export function cleanEnvValue(val?: string | null): string | null {
  if (!val || typeof val !== 'string') return null;
  const trimmed = val.trim();
  if (!trimmed) return null;
  const unquoted = trimmed.replace(/^["']|["']$/g, '').trim();
  return unquoted || null;
}

/**
 * Validates that the provided redirect URL is an absolute, well-formed HTTP/HTTPS URL.
 */
export function validateAuthRedirectUrl(
  rawUrl?: string | null
): AuthRedirectValidationResult {
  const cleaned = cleanEnvValue(rawUrl);
  if (!cleaned) {
    return {
      isValid: false,
      error:
        'AUTH_REDIRECT_URL is not configured. An explicit, absolute redirect URL (e.g. http://16.113.92.222/auth/callback) is recommended.',
      url: null,
      origin: null,
    };
  }

  try {
    const parsed = new URL(cleaned);

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
      error: `AUTH_REDIRECT_URL "${cleaned}" is not a valid absolute URL.`,
      url: null,
      origin: null,
    };
  }
}

export const CANONICAL_AWS_ORIGIN = 'http://16.113.92.222';
export const CANONICAL_AWS_CALLBACK = `${CANONICAL_AWS_ORIGIN}/auth/callback`;

/**
 * Authoritative allowed origins for application deployments.
 * Only the canonical AWS EC2 origin and local development hosts are permitted.
 */
export const DEFAULT_ALLOWED_ORIGINS = [
  CANONICAL_AWS_ORIGIN,
  'http://localhost:3000',
  'http://127.0.0.1:3000',
];

/**
 * Helper to determine whether the current process is genuinely running
 * inside an active Vercel platform runtime.
 *
 * Security Invariant:
 * - NEXT_PUBLIC_VERCEL_ENV alone does NOT activate Vercel fallback.
 * - Must have explicit VERCEL === '1' AND a non-empty VERCEL_URL.
 */
export function isVercelRuntime(): boolean {
  const isVercel = cleanEnvValue(process.env.VERCEL) === '1';
  const vercelUrl = cleanEnvValue(process.env.VERCEL_URL);
  return isVercel && Boolean(vercelUrl);
}

export interface GetAuthRedirectUrlOptions {
  fallbackOrigin?: string | null;
  preserveParams?: boolean;
  next?: string | null;
}

/**
 * Returns the canonical authentication redirect URL for Supabase Auth flows
 * (e.g. emailRedirectTo during signup, OAuth redirectTo).
 *
 * Guarantees a validated redirect URL pointing to /auth/callback on the AWS EC2 deployment.
 *
 * Priority order:
 * 1. Explicit AUTH_REDIRECT_URL or NEXT_PUBLIC_AUTH_REDIRECT_URL from environment (always wins)
 * 2. Standard host environment variables (FRONTEND_URL or NEXT_PUBLIC_APP_URL)
 * 3. Isolated Vercel runtime (ONLY when VERCEL === '1' and VERCEL_URL is set, and no AWS vars exist)
 * 4. Request-derived fallbackOrigin ONLY IF in allowed origins list (e.g. localhost:3000 in dev)
 * 5. Canonical EC2 destination: http://16.113.92.222/auth/callback
 */
export function getAuthRedirectUrl(
  optionsOrFallbackOrigin?: string | null | GetAuthRedirectUrlOptions
): string {
  let fallbackOrigin: string | null = null;
  let preserveParams = false;
  let nextTarget: string | null = null;

  if (typeof optionsOrFallbackOrigin === 'string') {
    fallbackOrigin = optionsOrFallbackOrigin;
  } else if (optionsOrFallbackOrigin && typeof optionsOrFallbackOrigin === 'object') {
    fallbackOrigin = optionsOrFallbackOrigin.fallbackOrigin || null;
    preserveParams = Boolean(optionsOrFallbackOrigin.preserveParams);
    if (optionsOrFallbackOrigin.next) {
      const cleanNext = optionsOrFallbackOrigin.next.trim();
      if (cleanNext.startsWith('/') && !cleanNext.startsWith('//') && !cleanNext.includes('\\')) {
        nextTarget = cleanNext;
      }
    }
  }

  const appendNext = (baseUrl: string): string => {
    if (!nextTarget) return baseUrl;
    try {
      const u = new URL(baseUrl);
      if (!u.searchParams.has('next')) {
        u.searchParams.set('next', nextTarget);
      }
      return u.toString();
    } catch (_) {
      const sep = baseUrl.includes('?') ? '&' : '?';
      return `${baseUrl}${sep}next=${encodeURIComponent(nextTarget)}`;
    }
  };

  // 1. Explicit AUTH_REDIRECT_URL or NEXT_PUBLIC_AUTH_REDIRECT_URL from environment (always wins)
  const rawEnvUrl =
    cleanEnvValue(process.env.AUTH_REDIRECT_URL) ||
    cleanEnvValue(process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL);
  if (rawEnvUrl) {
    try {
      const parsed = new URL(rawEnvUrl);
      if ((parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.hostname) {
        if (preserveParams && (parsed.search || parsed.hash)) {
          const fullUrl = `${parsed.origin}/auth/callback${parsed.search}${parsed.hash}`;
          return appendNext(fullUrl);
        }
        return appendNext(`${parsed.origin}/auth/callback`);
      } else {
        throw new Error(`Invalid protocol or host: ${rawEnvUrl}`);
      }
    } catch (err) {
      console.error(
        `[auth-redirect] Configured AUTH_REDIRECT_URL "${rawEnvUrl}" is invalid or malformed (${err}). Falling back strictly to canonical AWS callback to prevent unsafe redirection.`
      );
      return appendNext(CANONICAL_AWS_CALLBACK);
    }
  }

  // 2. Standard deployment host environment variables (FRONTEND_URL / NEXT_PUBLIC_APP_URL)
  const hostUrl =
    cleanEnvValue(process.env.FRONTEND_URL) ||
    cleanEnvValue(process.env.NEXT_PUBLIC_APP_URL);
  if (hostUrl) {
    try {
      const parsed = new URL(hostUrl);
      if ((parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.hostname) {
        return appendNext(`${parsed.origin}/auth/callback`);
      } else {
        throw new Error(`Invalid protocol or host: ${hostUrl}`);
      }
    } catch (err) {
      console.error(
        `[auth-redirect] Configured FRONTEND_URL/NEXT_PUBLIC_APP_URL "${hostUrl}" is invalid (${err}). Falling back strictly to canonical AWS callback.`
      );
      return appendNext(CANONICAL_AWS_CALLBACK);
    }
  }

  // 3. Isolated Vercel runtime fallback
  // Activated ONLY when running explicitly inside Vercel platform runtime (VERCEL === '1') with VERCEL_URL.
  // NEXT_PUBLIC_VERCEL_ENV alone does NOT activate this.
  if (isVercelRuntime()) {
    try {
      const vercelHost = cleanEnvValue(process.env.VERCEL_URL)!;
      const vercelOrigin = new URL(`https://${vercelHost}`).origin;
      return appendNext(`${vercelOrigin}/auth/callback`);
    } catch (_) {}
  }

  // 4. Request-derived fallback origin, strictly validated against allowed origins
  const cleanFallback = cleanEnvValue(fallbackOrigin);
  if (cleanFallback) {
    let candidateOrigin: string | null = null;
    try {
      const parsed = new URL(cleanFallback);
      if ((parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.hostname) {
        candidateOrigin = parsed.origin;
      }
    } catch (_) {
      try {
        const parsed = new URL(`http://${cleanFallback}`);
        if (parsed.hostname) {
          candidateOrigin = parsed.origin;
        }
      } catch (_) {}
    }

    if (candidateOrigin) {
      const allowed = getAllowedOrigins();
      const isAllowed = allowed.some(
        (o) => o.toLowerCase() === candidateOrigin!.toLowerCase()
      );
      if (isAllowed) {
        return appendNext(`${candidateOrigin}/auth/callback`);
      }
    }
  }

  // 5. Canonical fallback for AWS EC2
  return appendNext(CANONICAL_AWS_CALLBACK);
}

/**
 * Returns a list of trusted allowed origins, dynamically including the
 * origin of the currently configured AUTH_REDIRECT_URL, FRONTEND_URL, or NEXT_PUBLIC_APP_URL.
 */
export function getAllowedOrigins(configuredUrl?: string | null): string[] {
  const origins = new Set<string>(DEFAULT_ALLOWED_ORIGINS);

  const candidates = [
    cleanEnvValue(configuredUrl),
    cleanEnvValue(process.env.AUTH_REDIRECT_URL),
    cleanEnvValue(process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL),
    cleanEnvValue(process.env.FRONTEND_URL),
    cleanEnvValue(process.env.NEXT_PUBLIC_APP_URL),
  ];

  for (const target of candidates) {
    if (target) {
      try {
        const parsed = new URL(target);
        if (
          parsed.origin &&
          parsed.origin !== 'null' &&
          (parsed.protocol === 'http:' || parsed.protocol === 'https:')
        ) {
          origins.add(parsed.origin);
        }
      } catch (_) {}
    }
  }

  // Only include dynamic Vercel origin if actively running on Vercel platform runtime
  if (isVercelRuntime()) {
    try {
      const vercelUrl = cleanEnvValue(process.env.VERCEL_URL);
      if (vercelUrl) {
        const vercelOrigin = new URL(`https://${vercelUrl}`).origin;
        origins.add(vercelOrigin);
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
      // Prevent protocol-relative path bypass (e.g. http://16.113.92.222//evil.com -> //evil.com)
      const cleanPath = parsed.pathname.startsWith('//')
        ? parsed.pathname.replace(/^\/+/, '/')
        : parsed.pathname;
      return cleanPath + parsed.search + parsed.hash;
    }
  } catch (_) {}

  // Untrusted destination fallback
  return '/dashboard';
}
