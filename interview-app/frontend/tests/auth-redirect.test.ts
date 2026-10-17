import { describe, it, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  validateAuthRedirectUrl,
  getAuthRedirectUrl,
  getAllowedOrigins,
  validateRedirectDestination,
  isVercelRuntime,
  CANONICAL_AWS_ORIGIN,
  CANONICAL_AWS_CALLBACK,
  DEFAULT_ALLOWED_ORIGINS,
} from '../src/utils/auth-redirect.ts';

describe('Authentication Redirect Utilities (AWS EC2 Canonical)', () => {
  const originalAuthEnv = process.env.AUTH_REDIRECT_URL;
  const originalNextPublicAuthEnv = process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL;
  const originalFrontendEnv = process.env.FRONTEND_URL;
  const originalAppUrlEnv = process.env.NEXT_PUBLIC_APP_URL;
  const originalVercelUrl = process.env.VERCEL_URL;
  const originalVercelFlag = process.env.VERCEL;
  const originalNextPublicVercelEnv = process.env.NEXT_PUBLIC_VERCEL_ENV;

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
    if (originalVercelUrl !== undefined) {
      process.env.VERCEL_URL = originalVercelUrl;
    } else {
      delete process.env.VERCEL_URL;
    }
    if (originalVercelFlag !== undefined) {
      process.env.VERCEL = originalVercelFlag;
    } else {
      delete process.env.VERCEL;
    }
    if (originalNextPublicVercelEnv !== undefined) {
      process.env.NEXT_PUBLIC_VERCEL_ENV = originalNextPublicVercelEnv;
    } else {
      delete process.env.NEXT_PUBLIC_VERCEL_ENV;
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

    it('should accept localhost URL for development', () => {
      const res = validateAuthRedirectUrl('http://localhost:3000/auth/callback');
      assert.equal(res.isValid, true);
      assert.equal(res.origin, 'http://localhost:3000');
    });
  });

  describe('isVercelRuntime', () => {
    it('returns false when VERCEL is not "1"', () => {
      delete process.env.VERCEL;
      process.env.VERCEL_URL = 'preview.vercel.app';
      assert.equal(isVercelRuntime(), false);
    });

    it('returns false when NEXT_PUBLIC_VERCEL_ENV is set but VERCEL is not "1"', () => {
      delete process.env.VERCEL;
      process.env.NEXT_PUBLIC_VERCEL_ENV = 'preview';
      process.env.VERCEL_URL = 'preview.vercel.app';
      assert.equal(isVercelRuntime(), false);
    });

    it('returns false when VERCEL is "1" but VERCEL_URL is missing or empty', () => {
      process.env.VERCEL = '1';
      delete process.env.VERCEL_URL;
      assert.equal(isVercelRuntime(), false);

      process.env.VERCEL_URL = '   ';
      assert.equal(isVercelRuntime(), false);
    });

    it('returns true ONLY when VERCEL is "1" and VERCEL_URL is non-empty', () => {
      process.env.VERCEL = '1';
      process.env.VERCEL_URL = 'my-app.vercel.app';
      assert.equal(isVercelRuntime(), true);
    });
  });

  describe('getAuthRedirectUrl (AWS EC2 Canonical Resolution)', () => {
    it('should resolve to /auth/callback when AUTH_REDIRECT_URL is configured', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback?next=/dashboard';
      const url = getAuthRedirectUrl();
      assert.equal(url, 'http://16.113.92.222/auth/callback');
    });

    it('should preserve query parameters when preserveParams: true is passed', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback?next=/dashboard';
      const url = getAuthRedirectUrl({ preserveParams: true });
      assert.equal(url, 'http://16.113.92.222/auth/callback?next=/dashboard');
    });

    it('should append next: /dashboard when explicitly passed in options', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      const url = getAuthRedirectUrl({ next: '/dashboard' });
      assert.equal(url, 'http://16.113.92.222/auth/callback?next=%2Fdashboard');
    });

    it('should normalize base domain without path to /auth/callback', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222';
      const url = getAuthRedirectUrl();
      assert.equal(url, 'http://16.113.92.222/auth/callback');
    });

    it('should respect FRONTEND_URL when AUTH_REDIRECT_URL is unset', () => {
      delete process.env.AUTH_REDIRECT_URL;
      process.env.FRONTEND_URL = 'http://16.113.92.222';
      const url = getAuthRedirectUrl();
      assert.equal(url, 'http://16.113.92.222/auth/callback');
    });

    it('should fallback to trusted request-derived fallbackOrigin if env is unset', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      const url = getAuthRedirectUrl('http://16.113.92.222');
      assert.equal(url, 'http://16.113.92.222/auth/callback');
    });

    it('should fallback to localhost if fallbackOrigin is localhost:3000 in dev', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      const url = getAuthRedirectUrl('http://localhost:3000');
      assert.equal(url, 'http://localhost:3000/auth/callback');
    });

    it('should REJECT untrusted fallbackOrigin (Host header injection prevention)', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      const url = getAuthRedirectUrl('http://evil.com');
      assert.notEqual(url, 'http://evil.com/auth/callback');
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('should fallback to canonical EC2 address if no environment variables are present', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.NEXT_PUBLIC_APP_URL;
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    // ── Regression: Explicit AWS Redirect Taking Precedence Over All Fallbacks ──
    it('REGRESSION: explicit AWS redirect takes absolute precedence over VERCEL_URL, FRONTEND_URL, and fallbackOrigin', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback';
      process.env.FRONTEND_URL = 'https://other-deployment.com';
      process.env.VERCEL = '1';
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';
      process.env.NEXT_PUBLIC_VERCEL_ENV = 'preview';

      const url = getAuthRedirectUrl('http://localhost:3000');
      assert.equal(url, 'http://16.113.92.222/auth/callback');
    });

    // ── Regression: VERCEL_URL Present on AWS with No Vercel Runtime Flag ──
    it('REGRESSION: VERCEL_URL present on AWS without VERCEL=1 NEVER activates Vercel redirect', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.VERCEL; // No VERCEL runtime flag
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';

      const url = getAuthRedirectUrl();
      assert.equal(url.includes('vercel.app'), false);
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    // ── Regression: NEXT_PUBLIC_VERCEL_ENV Present or Empty on AWS ──
    it('REGRESSION: NEXT_PUBLIC_VERCEL_ENV present or empty on AWS NEVER activates Vercel redirect', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.VERCEL;

      // Case A: NEXT_PUBLIC_VERCEL_ENV is preview
      process.env.NEXT_PUBLIC_VERCEL_ENV = 'preview';
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';
      assert.equal(getAuthRedirectUrl(), CANONICAL_AWS_CALLBACK);

      // Case B: NEXT_PUBLIC_VERCEL_ENV is production
      process.env.NEXT_PUBLIC_VERCEL_ENV = 'production';
      assert.equal(getAuthRedirectUrl(), CANONICAL_AWS_CALLBACK);

      // Case C: NEXT_PUBLIC_VERCEL_ENV is empty string
      process.env.NEXT_PUBLIC_VERCEL_ENV = '';
      assert.equal(getAuthRedirectUrl(), CANONICAL_AWS_CALLBACK);
    });

    // ── Regression: Missing and Malformed Redirect Configuration ──
    it('REGRESSION: malformed AUTH_REDIRECT_URL produces safe canonical fallback and does NOT select secondary untrusted fallback', () => {
      delete process.env.FRONTEND_URL;
      process.env.AUTH_REDIRECT_URL = 'not-a-valid-url';

      // Even if an attacker passes fallbackOrigin, malformed AUTH_REDIRECT_URL must safely fallback to canonical AWS
      const url = getAuthRedirectUrl('http://attacker.com');
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('REGRESSION: non-http protocol in AUTH_REDIRECT_URL produces safe canonical fallback', () => {
      delete process.env.FRONTEND_URL;
      process.env.AUTH_REDIRECT_URL = 'ftp://malicious.host/auth/callback';

      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    // ── Regression: Host-Header and Forwarded-Header Injection ──
    it('REGRESSION: reject spoofed subdomains and host header injection variants', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;

      const hostileOrigins = [
        'http://evil.com',
        'http://16.113.92.222.attacker.com',
        'http://localhost.attacker.com',
        'http://16.113.92.222:8080',
        'http://attacker.com/16.113.92.222',
        'https://interview-prep-saicharanyadavallis-projects.vercel.app',
      ];

      for (const hostile of hostileOrigins) {
        const url = getAuthRedirectUrl(hostile);
        assert.equal(url, CANONICAL_AWS_CALLBACK, `Failed to reject hostile origin: ${hostile}`);
      }
    });

    // ── Regression: Signup Confirmation and Google OAuth Callbacks ──
    it('REGRESSION: signup confirmation and Google OAuth preserve next=/dashboard destination', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback?next=/dashboard';
      
      // Signup flow uses preserveParams: true
      const signupUrl = getAuthRedirectUrl({
        fallbackOrigin: 'http://16.113.92.222',
        preserveParams: true,
        next: '/dashboard',
      });
      assert.equal(signupUrl, 'http://16.113.92.222/auth/callback?next=/dashboard');

      // Google OAuth flow passes next: '/dashboard'
      const oauthUrl = getAuthRedirectUrl({
        fallbackOrigin: 'http://16.113.92.222',
        next: '/dashboard',
      });
      assert.equal(oauthUrl, 'http://16.113.92.222/auth/callback?next=%2Fdashboard');
    });

    // ── Isolated Vercel Support ──
    it('ISOLATED VERCEL: only activated when explicitly running in Vercel container (VERCEL===1) with no AWS env', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      process.env.VERCEL = '1';
      process.env.VERCEL_URL = 'interview-prep-isolated.vercel.app';

      const url = getAuthRedirectUrl();
      assert.equal(url, 'https://interview-prep-isolated.vercel.app/auth/callback');
    });
  });

  describe('getAllowedOrigins', () => {
    it('should include canonical AWS origin and localhost only by default', () => {
      const origins = getAllowedOrigins();
      assert.ok(origins.includes('http://16.113.92.222'));
      assert.ok(origins.includes('http://localhost:3000'));
      assert.ok(origins.includes('http://127.0.0.1:3000'));
      assert.equal(origins.some((o) => o.includes('vercel.app')), false);
    });

    it('should include origin from custom configured URL', () => {
      const origins = getAllowedOrigins('https://custom-domain.com/auth/callback');
      assert.ok(origins.includes('https://custom-domain.com'));
    });

    it('should include origin from FRONTEND_URL environment variable', () => {
      process.env.FRONTEND_URL = 'http://16.113.92.222';
      const origins = getAllowedOrigins();
      assert.ok(origins.includes('http://16.113.92.222'));
    });

    it('should NOT include Vercel origin when VERCEL_URL is set but VERCEL!=1', () => {
      delete process.env.VERCEL;
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';
      const origins = getAllowedOrigins();
      assert.equal(origins.some((o) => o.includes('vercel.app')), false);
    });

    it('should include Vercel origin ONLY when VERCEL===1', () => {
      process.env.VERCEL = '1';
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';
      const origins = getAllowedOrigins();
      assert.ok(origins.includes('https://interview-prep-preview.vercel.app'));
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

    it('should block former Vercel deployment URLs and fallback to /dashboard on AWS', () => {
      assert.equal(
        validateRedirectDestination('https://interview-prep-saicharanyadavallis-projects.vercel.app/dashboard'),
        '/dashboard'
      );
      assert.equal(
        validateRedirectDestination('https://interview-prep-kappa-sandy.vercel.app/'),
        '/dashboard'
      );
    });

    it('should block javascript: URI scheme', () => {
      assert.equal(validateRedirectDestination('javascript:alert(document.cookie)'), '/dashboard');
    });

    it('should allow absolute URLs matching canonical AWS deployment origin and strip to safe path', () => {
      assert.equal(
        validateRedirectDestination('http://16.113.92.222/dashboard'),
        '/dashboard'
      );
      assert.equal(
        validateRedirectDestination('http://16.113.92.222/solve?q=42'),
        '/solve?q=42'
      );
      assert.equal(
        validateRedirectDestination('http://localhost:3000/profile'),
        '/profile'
      );
    });
  });
});
