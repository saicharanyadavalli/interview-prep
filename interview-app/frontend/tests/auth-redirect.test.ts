import { describe, it, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  validateAuthRedirectUrl,
  getAuthRedirectUrl,
  getAllowedOrigins,
  validateRedirectDestination,
  CANONICAL_AWS_ORIGIN,
  CANONICAL_AWS_CALLBACK,
  DEFAULT_ALLOWED_ORIGINS,
} from '../src/utils/auth-redirect.ts';

describe('Authentication Redirect Utilities', () => {
  const originalAuthEnv = process.env.AUTH_REDIRECT_URL;
  const originalNextPublicAuthEnv = process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL;
  const originalVercelEnv = process.env.VERCEL_URL;
  const originalVercelFlag = process.env.VERCEL;
  const originalFrontendEnv = process.env.FRONTEND_URL;
  const originalAppUrlEnv = process.env.NEXT_PUBLIC_APP_URL;

  afterEach(() => {
    if (originalAuthEnv !== undefined) {
      process.env.AUTH_REDIRECT_URL = originalAuthEnv;
    } else {
      delete process.env.AUTH_REDIRECT_URL;
    }
    if (originalNextPublicAuthEnv !== undefined) {
      process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL = originalNextPublicAuthEnv;
    } else {
      delete process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL;
    }
    if (originalVercelEnv !== undefined) {
      process.env.VERCEL_URL = originalVercelEnv;
    } else {
      delete process.env.VERCEL_URL;
    }
    if (originalVercelFlag !== undefined) {
      process.env.VERCEL = originalVercelFlag;
    } else {
      delete process.env.VERCEL;
    }
    if (originalFrontendEnv !== undefined) {
      process.env.FRONTEND_URL = originalFrontendEnv;
    } else {
      delete process.env.FRONTEND_URL;
    }
    if (originalAppUrlEnv !== undefined) {
      process.env.NEXT_PUBLIC_APP_URL = originalAppUrlEnv;
    } else {
      delete process.env.NEXT_PUBLIC_APP_URL;
    }
  });

  describe('validateAuthRedirectUrl', () => {
    it('should return error when AUTH_REDIRECT_URL is missing or empty', () => {
      const resNull = validateAuthRedirectUrl(null);
      assert.equal(resNull.isValid, false);
      assert.ok(resNull.error?.includes('AUTH_REDIRECT_URL is not configured'));

      const resEmpty = validateAuthRedirectUrl('   ');
      assert.equal(resEmpty.isValid, false);
      assert.ok(resEmpty.error?.includes('AUTH_REDIRECT_URL is not configured'));
    });

    it('should reject invalid URL syntax', () => {
      const res = validateAuthRedirectUrl('not-a-valid-url');
      assert.equal(res.isValid, false);
      assert.ok(res.error?.includes('is not a valid absolute URL'));
    });

    it('should reject non-http/https protocols (e.g. javascript, ftp)', () => {
      const resFtp = validateAuthRedirectUrl('ftp://16.113.92.222/callback');
      assert.equal(resFtp.isValid, false);
      assert.ok(resFtp.error?.includes('must use http or https'));

      const resJs = validateAuthRedirectUrl('javascript:alert(1)');
      assert.equal(resJs.isValid, false);
      assert.ok(resJs.error?.includes('must use http or https'));
    });

    it('should accept valid EC2 HTTP URL', () => {
      const res = validateAuthRedirectUrl('http://16.113.92.222/auth/callback');
      assert.equal(res.isValid, true);
      assert.equal(res.error, null);
      assert.equal(res.origin, 'http://16.113.92.222');
      assert.equal(res.url, 'http://16.113.92.222/auth/callback');
    });

    it('should accept valid Vercel HTTPS URL', () => {
      const url = 'https://interview-prep-saicharanyadavallis-projects.vercel.app/auth/callback';
      const res = validateAuthRedirectUrl(url);
      assert.equal(res.isValid, true);
      assert.equal(res.error, null);
      assert.equal(res.origin, 'https://interview-prep-saicharanyadavallis-projects.vercel.app');
      assert.equal(res.url, url);
    });

    it('should accept localhost URL for development', () => {
      const res = validateAuthRedirectUrl('http://localhost:3000/auth/callback');
      assert.equal(res.isValid, true);
      assert.equal(res.origin, 'http://localhost:3000');
    });
  });

  describe('getAuthRedirectUrl (Deployment-Safe Resolution)', () => {
    it('should cleanly resolve to /auth/callback when AUTH_REDIRECT_URL is configured', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback?next=/dashboard';
      const url = getAuthRedirectUrl();
      assert.equal(url, 'http://16.113.92.222/auth/callback');
    });

    it('should preserve query parameters when preserveParams: true is passed', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback?next=/dashboard';
      const url = getAuthRedirectUrl({ preserveParams: true });
      assert.equal(url, 'http://16.113.92.222/auth/callback?next=/dashboard');
    });

    it('should normalize base domain without path to /auth/callback', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222';
      const url = getAuthRedirectUrl();
      assert.equal(url, 'http://16.113.92.222/auth/callback');
    });

    it('AWS AUTH_REDIRECT_URL wins even if VERCEL_URL is also set in environment', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback';
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';
      const url = getAuthRedirectUrl();
      assert.equal(url, 'http://16.113.92.222/auth/callback');
    });

    it('should fallback to trusted request-derived fallbackOrigin if env is unset', () => {
      delete process.env.AUTH_REDIRECT_URL;
      const url = getAuthRedirectUrl('http://16.113.92.222');
      assert.equal(url, 'http://16.113.92.222/auth/callback');
    });

    it('should fallback to localhost if fallbackOrigin is localhost:3000', () => {
      delete process.env.AUTH_REDIRECT_URL;
      const url = getAuthRedirectUrl('http://localhost:3000');
      assert.equal(url, 'http://localhost:3000/auth/callback');
    });

    it('should REJECT untrusted fallbackOrigin (Host header injection prevention)', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      // Hostile domain should not be accepted as redirect destination
      const url = getAuthRedirectUrl('http://evil.com');
      assert.notEqual(url, 'http://evil.com/auth/callback');
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('should not fallback to VERCEL_URL on AWS even if VERCEL_URL exists, unless VERCEL===1', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.VERCEL;
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';

      // On non-Vercel environment (AWS), should NOT leak to Vercel
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('should fallback to Vercel deployment URL ONLY when VERCEL===1', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      process.env.VERCEL = '1';
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';

      const url = getAuthRedirectUrl();
      assert.equal(url, 'https://interview-prep-preview.vercel.app/auth/callback');
    });

    it('should fallback to canonical EC2 address if no environment variables are present', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.VERCEL_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.VERCEL;
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });
  });

  describe('getAllowedOrigins', () => {
    it('should include default deployment origins', () => {
      const origins = getAllowedOrigins();
      assert.ok(origins.includes('http://16.113.92.222'));
      assert.ok(origins.includes('https://interview-prep-saicharanyadavallis-projects.vercel.app'));
      assert.ok(origins.includes('http://localhost:3000'));
    });

    it('should include origin from custom configured URL', () => {
      const origins = getAllowedOrigins('https://custom-domain.com/auth/callback');
      assert.ok(origins.includes('https://custom-domain.com'));
    });

    it('should include origin from FRONTEND_URL environment variable', () => {
      process.env.FRONTEND_URL = 'http://13.200.50.25';
      const origins = getAllowedOrigins();
      assert.ok(origins.includes('http://13.200.50.25'));
    });
  });

  describe('validateRedirectDestination (Open-Redirect Prevention)', () => {
    it('should fallback to /dashboard for empty, null, or undefined input', () => {
      assert.equal(validateRedirectDestination(null), '/dashboard');
      assert.equal(validateRedirectDestination(undefined), '/dashboard');
      assert.equal(validateRedirectDestination(''), '/dashboard');
      assert.equal(validateRedirectDestination('   '), '/dashboard');
    });

    it('should accept valid relative paths', () => {
      assert.equal(validateRedirectDestination('/dashboard'), '/dashboard');
      assert.equal(validateRedirectDestination('/practice'), '/practice');
      assert.equal(
        validateRedirectDestination('/questions?topic=arrays&difficulty=Medium#sol'),
        '/questions?topic=arrays&difficulty=Medium#sol'
      );
    });

    it('should block protocol-relative open-redirect attacks (//evil.com)', () => {
      assert.equal(validateRedirectDestination('//evil.com'), '/dashboard');
      assert.equal(validateRedirectDestination('//evil.com/phishing'), '/dashboard');
    });

    it('should block backslash open-redirect attacks (\\evil.com, /\\evil.com)', () => {
      assert.equal(validateRedirectDestination('\\evil.com'), '/dashboard');
      assert.equal(validateRedirectDestination('/\\evil.com'), '/dashboard');
      assert.equal(validateRedirectDestination('\\\\evil.com'), '/dashboard');
    });

    it('should block external untrusted absolute URLs', () => {
      assert.equal(validateRedirectDestination('https://evil.com'), '/dashboard');
      assert.equal(validateRedirectDestination('https://attacker.com/steal-token'), '/dashboard');
      assert.equal(validateRedirectDestination('http://malicious-site.org'), '/dashboard');
    });

    it('should block javascript: URI scheme', () => {
      assert.equal(validateRedirectDestination('javascript:alert(document.cookie)'), '/dashboard');
    });

    it('should allow absolute URLs matching allowed deployment origins and strip to safe path', () => {
      assert.equal(
        validateRedirectDestination('http://16.113.92.222/dashboard'),
        '/dashboard'
      );
      assert.equal(
        validateRedirectDestination('https://interview-prep-saicharanyadavallis-projects.vercel.app/solve?q=42'),
        '/solve?q=42'
      );
      assert.equal(
        validateRedirectDestination('http://localhost:3000/profile'),
        '/profile'
      );
    });
  });
});
