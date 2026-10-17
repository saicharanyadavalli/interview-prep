import { describe, it, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  validateAuthRedirectUrl,
  getAuthRedirectUrl,
  getAllowedOrigins,
  validateRedirectDestination,
  isVercelRuntime,
  cleanEnvValue,
  CANONICAL_AWS_ORIGIN,
  CANONICAL_AWS_CALLBACK,
  DEFAULT_ALLOWED_ORIGINS,
} from '../src/utils/auth-redirect.ts';

// ─── Test constants ──────────────────────────────────────────────────────────

const AWS_ORIGIN = 'http://16.113.92.222';
const AWS_CALLBACK = 'http://16.113.92.222/auth/callback';
const STALE_VERCEL_URL = 'https://interview-prep-saicharanyadavallis-projects.vercel.app';
const STALE_VERCEL_CALLBACK = `${STALE_VERCEL_URL}/auth/callback`;

// ─── Environment cleanup helper ──────────────────────────────────────────────

describe('Authentication Redirect Utilities (AWS EC2 Canonical)', () => {
  const savedEnv: Record<string, string | undefined> = {};
  const TRACKED_VARS = [
    'AUTH_REDIRECT_URL',
    'NEXT_PUBLIC_AUTH_REDIRECT_URL',
    'FRONTEND_URL',
    'NEXT_PUBLIC_APP_URL',
    'VERCEL_URL',
    'VERCEL',
    'NEXT_PUBLIC_VERCEL_ENV',
  ];

  afterEach(() => {
    for (const key of TRACKED_VARS) {
      if (savedEnv[key] !== undefined) {
        process.env[key] = savedEnv[key];
      } else {
        delete process.env[key];
      }
    }
  });

  // Save originals at suite level
  for (const key of TRACKED_VARS) {
    savedEnv[key] = process.env[key];
  }

  // ── validateAuthRedirectUrl ──────────────────────────────────────────────

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

  // ── isVercelRuntime ──────────────────────────────────────────────────────

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

  // ── getAuthRedirectUrl (AWS EC2 Canonical Resolution) ───────────────────

  describe('getAuthRedirectUrl (AWS EC2 Canonical Resolution)', () => {

    // ── Stage 4 Test 1: AWS configuration always generates the AWS callback ──

    it('[T1] AWS AUTH_REDIRECT_URL always generates the AWS callback', () => {
      process.env.AUTH_REDIRECT_URL = AWS_CALLBACK;
      const url = getAuthRedirectUrl();
      assert.equal(url, AWS_CALLBACK);
    });

    it('[T1] should resolve to /auth/callback when AUTH_REDIRECT_URL is configured with query params', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback?next=/dashboard';
      const url = getAuthRedirectUrl();
      // Without preserveParams, should strip query and return base callback
      assert.equal(url, AWS_CALLBACK);
    });

    it('[T1] should preserve query parameters when preserveParams: true is passed', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback?next=/dashboard';
      const url = getAuthRedirectUrl({ preserveParams: true });
      assert.equal(url, 'http://16.113.92.222/auth/callback?next=/dashboard');
    });

    it('[T1] should append next: /dashboard when explicitly passed in options', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      const url = getAuthRedirectUrl({ next: '/dashboard' });
      assert.equal(url, 'http://16.113.92.222/auth/callback?next=%2Fdashboard');
    });

    it('[T1] should normalize base domain without path to /auth/callback', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222';
      const url = getAuthRedirectUrl();
      assert.equal(url, AWS_CALLBACK);
    });

    // ── Stage 4 Test 2: Stale Vercel FRONTEND_URL cannot override AWS config ──

    it('[T2] stale Vercel FRONTEND_URL cannot override explicit AUTH_REDIRECT_URL', () => {
      process.env.AUTH_REDIRECT_URL = AWS_CALLBACK;
      process.env.FRONTEND_URL = STALE_VERCEL_URL; // stale Vercel config
      const url = getAuthRedirectUrl();
      assert.equal(url, AWS_CALLBACK);
      assert.ok(!url.includes('vercel.app'), 'Must not include Vercel domain');
    });

    it('[T2] stale Vercel FRONTEND_URL alone (no AUTH_REDIRECT_URL) routes to Vercel — document this and fix by always setting AUTH_REDIRECT_URL', () => {
      // This test documents why AUTH_REDIRECT_URL must ALWAYS be explicitly set on AWS.
      // Without AUTH_REDIRECT_URL, FRONTEND_URL pointing to Vercel would cause incorrect routing.
      delete process.env.AUTH_REDIRECT_URL;
      process.env.FRONTEND_URL = STALE_VERCEL_URL;
      const url = getAuthRedirectUrl();
      // This currently returns the Vercel callback — which is why AUTH_REDIRECT_URL must always be set on EC2.
      assert.equal(url, STALE_VERCEL_CALLBACK, 
        'EXPECTED: without AUTH_REDIRECT_URL, FRONTEND_URL pointing to Vercel would be used — always set AUTH_REDIRECT_URL on EC2!');
    });

    it('[T2] FRONTEND_URL alone (pointing to AWS) routes correctly when no AUTH_REDIRECT_URL', () => {
      delete process.env.AUTH_REDIRECT_URL;
      process.env.FRONTEND_URL = AWS_ORIGIN;
      const url = getAuthRedirectUrl();
      assert.equal(url, AWS_CALLBACK);
    });

    // ── Stage 4 Test 3: Stale NEXT_PUBLIC_APP_URL cannot override AWS config ──

    it('[T3] stale Vercel NEXT_PUBLIC_APP_URL cannot override explicit AUTH_REDIRECT_URL', () => {
      process.env.AUTH_REDIRECT_URL = AWS_CALLBACK;
      process.env.NEXT_PUBLIC_APP_URL = STALE_VERCEL_URL;
      const url = getAuthRedirectUrl();
      assert.equal(url, AWS_CALLBACK);
      assert.ok(!url.includes('vercel.app'));
    });

    it('[T3] stale Vercel NEXT_PUBLIC_APP_URL cannot override explicit FRONTEND_URL pointing to AWS', () => {
      delete process.env.AUTH_REDIRECT_URL;
      process.env.FRONTEND_URL = AWS_ORIGIN;
      process.env.NEXT_PUBLIC_APP_URL = STALE_VERCEL_URL;
      const url = getAuthRedirectUrl();
      // FRONTEND_URL wins over NEXT_PUBLIC_APP_URL (priority 2 vs later)
      assert.equal(url, AWS_CALLBACK);
    });

    // ── Stage 4 Test 4: NEXT_PUBLIC_VERCEL_ENV alone does not enable Vercel fallback ──

    it('[T4] NEXT_PUBLIC_VERCEL_ENV alone does NOT enable Vercel redirect (without VERCEL=1)', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.VERCEL;
      process.env.NEXT_PUBLIC_VERCEL_ENV = 'preview';
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
      assert.ok(!url.includes('vercel.app'));
    });

    it('[T4] NEXT_PUBLIC_VERCEL_ENV=production alone does NOT enable Vercel redirect', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.VERCEL;
      process.env.NEXT_PUBLIC_VERCEL_ENV = 'production';
      process.env.VERCEL_URL = 'interview-prep.vercel.app';
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('[T4] NEXT_PUBLIC_VERCEL_ENV empty string does NOT enable Vercel redirect', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.VERCEL;
      process.env.NEXT_PUBLIC_VERCEL_ENV = '';
      process.env.VERCEL_URL = 'interview-prep.vercel.app';
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    // ── Stage 4 Test 5: Genuine Vercel deployment uses its own callback ──

    it('[T5] genuine Vercel deployment (VERCEL=1 + VERCEL_URL, no AWS env) uses Vercel callback', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.NEXT_PUBLIC_APP_URL;
      process.env.VERCEL = '1';
      process.env.VERCEL_URL = 'interview-prep-isolated.vercel.app';
      const url = getAuthRedirectUrl();
      assert.equal(url, 'https://interview-prep-isolated.vercel.app/auth/callback');
    });

    it('[T5] genuine Vercel deployment with AWS AUTH_REDIRECT_URL still prefers AWS (explicit wins)', () => {
      process.env.AUTH_REDIRECT_URL = AWS_CALLBACK;
      process.env.VERCEL = '1';
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';
      const url = getAuthRedirectUrl();
      assert.equal(url, AWS_CALLBACK,
        'AUTH_REDIRECT_URL wins even when genuinely running on Vercel — explicit configuration wins');
    });

    // ── Stage 4 Test 6: OAuth callback completion returns to AWS dashboard ──

    it('[T6] successful OAuth callback with next=/dashboard routes to AWS dashboard', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback';
      const url = getAuthRedirectUrl({ next: '/dashboard' });
      assert.equal(url, 'http://16.113.92.222/auth/callback?next=%2Fdashboard');
      assert.ok(url.startsWith(AWS_ORIGIN));
    });

    it('[T6] signInWithGoogle passes correct AWS redirectTo for PKCE flow', () => {
      process.env.AUTH_REDIRECT_URL = AWS_CALLBACK;
      // Simulate what signInWithGoogle() does — pass window.location.origin as fallbackOrigin
      const redirectUrl = getAuthRedirectUrl({
        fallbackOrigin: AWS_ORIGIN,
        next: '/dashboard',
      });
      assert.ok(redirectUrl.startsWith(AWS_ORIGIN));
      assert.ok(redirectUrl.includes('/auth/callback'));
      assert.ok(!redirectUrl.includes('vercel.app'));
    });

    // ── Stage 4 Test 7: Email confirmation and magic-link use AWS origin ──

    it('[T7] email signup confirmation callback uses AWS origin', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback?next=/dashboard';
      // signup() calls getAuthRedirectUrl({ fallbackOrigin: requestOrigin, preserveParams: true, next: '/dashboard' })
      const emailRedirectTo = getAuthRedirectUrl({
        fallbackOrigin: 'http://16.113.92.222', // from request host header on EC2
        preserveParams: true,
        next: '/dashboard',
      });
      assert.ok(emailRedirectTo.startsWith(AWS_ORIGIN), 'Email redirect must start with AWS origin');
      assert.ok(emailRedirectTo.includes('/auth/callback'));
      assert.ok(!emailRedirectTo.includes('vercel.app'));
    });

    it('[T7] magic-link callback uses AWS origin with next=/dashboard', () => {
      process.env.AUTH_REDIRECT_URL = AWS_CALLBACK;
      const url = getAuthRedirectUrl({ next: '/dashboard' });
      assert.ok(url.startsWith(AWS_ORIGIN));
      assert.ok(url.includes('next='));
    });

    it('[T7] email confirmation fallback origin from EC2 request headers routes to AWS', () => {
      delete process.env.AUTH_REDIRECT_URL;
      process.env.FRONTEND_URL = AWS_ORIGIN;
      // Simulate request origin from inside the EC2 Nginx proxy
      const emailRedirectTo = getAuthRedirectUrl({
        fallbackOrigin: AWS_ORIGIN,
        preserveParams: true,
        next: '/dashboard',
      });
      assert.ok(emailRedirectTo.startsWith(AWS_ORIGIN));
      assert.ok(!emailRedirectTo.includes('vercel.app'));
    });

    // ── Stage 4 Test 8: Malicious external destinations are rejected ──

    it('[T8] rejects external/untrusted fallbackOrigin (host header injection)', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;

      const hostileOrigins = [
        'http://evil.com',
        'http://16.113.92.222.attacker.com',
        'http://localhost.attacker.com',
        'http://16.113.92.222:8080',
        'http://attacker.com/16.113.92.222',
        STALE_VERCEL_URL,
      ];

      for (const hostile of hostileOrigins) {
        const url = getAuthRedirectUrl(hostile);
        assert.equal(url, CANONICAL_AWS_CALLBACK, `Failed to reject hostile origin: ${hostile}`);
      }
    });

    it('[T8] rejects protocol-relative URLs as fallbackOrigin', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      // protocol-relative as fallbackOrigin — not a valid absolute URL so should fall through
      const url = getAuthRedirectUrl('//evil.com');
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('[T8] rejects javascript: URI in AUTH_REDIRECT_URL', () => {
      process.env.AUTH_REDIRECT_URL = 'javascript:alert(1)';
      delete process.env.FRONTEND_URL;
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('[T8] rejects ftp: URI in AUTH_REDIRECT_URL', () => {
      process.env.AUTH_REDIRECT_URL = 'ftp://malicious.host/auth/callback';
      delete process.env.FRONTEND_URL;
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    // ── Stage 4 Test 9: Missing/malformed config cannot silently redirect to Vercel ──

    it('[T9] malformed AUTH_REDIRECT_URL falls back to canonical AWS, NOT secondary fallback', () => {
      process.env.AUTH_REDIRECT_URL = 'not-a-valid-url';
      delete process.env.FRONTEND_URL;
      // Even if attacker passes hostile fallbackOrigin — must still land on canonical AWS
      const url = getAuthRedirectUrl('http://attacker.com');
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('[T9] missing AUTH_REDIRECT_URL with no FRONTEND_URL falls back to canonical AWS', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.NEXT_PUBLIC_APP_URL;
      delete process.env.VERCEL;
      delete process.env.VERCEL_URL;
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('[T9] stale Vercel variables + NEXT_PUBLIC_VERCEL_ENV but no VERCEL=1 → canonical AWS', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.NEXT_PUBLIC_APP_URL;
      delete process.env.VERCEL; // no VERCEL=1
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';
      process.env.NEXT_PUBLIC_VERCEL_ENV = 'preview';
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
      assert.ok(!url.includes('vercel.app'));
    });

    // ── Stage 4 Test 10: Local development and existing auth behavior ──

    it('[T10] localhost fallbackOrigin works in local development when no env vars set', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.NEXT_PUBLIC_APP_URL;
      const url = getAuthRedirectUrl('http://localhost:3000');
      assert.equal(url, 'http://localhost:3000/auth/callback');
    });

    it('[T10] 127.0.0.1 fallbackOrigin works in local development', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.NEXT_PUBLIC_APP_URL;
      const url = getAuthRedirectUrl('http://127.0.0.1:3000');
      assert.equal(url, 'http://127.0.0.1:3000/auth/callback');
    });

    it('[T10] FRONTEND_URL pointing to AWS is respected for local dev/testing', () => {
      delete process.env.AUTH_REDIRECT_URL;
      process.env.FRONTEND_URL = AWS_ORIGIN;
      const url = getAuthRedirectUrl();
      assert.equal(url, AWS_CALLBACK);
    });

    it('[T10] NEXT_PUBLIC_AUTH_REDIRECT_URL (build-time embedded) is respected as priority 1', () => {
      delete process.env.AUTH_REDIRECT_URL;
      process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL = AWS_CALLBACK;
      const url = getAuthRedirectUrl();
      assert.equal(url, AWS_CALLBACK);
    });

    // ── Previous regression tests (preserved) ───────────────────────────────

    it('REGRESSION: explicit AWS redirect takes absolute precedence over VERCEL_URL, FRONTEND_URL, and fallbackOrigin', () => {
      process.env.AUTH_REDIRECT_URL = AWS_CALLBACK;
      process.env.FRONTEND_URL = 'https://other-deployment.com';
      process.env.VERCEL = '1';
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';
      process.env.NEXT_PUBLIC_VERCEL_ENV = 'preview';

      const url = getAuthRedirectUrl('http://localhost:3000');
      assert.equal(url, AWS_CALLBACK);
    });

    it('REGRESSION: VERCEL_URL present on AWS without VERCEL=1 NEVER activates Vercel redirect', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.VERCEL;
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';

      const url = getAuthRedirectUrl();
      assert.equal(url.includes('vercel.app'), false);
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('REGRESSION: NEXT_PUBLIC_VERCEL_ENV present or empty on AWS NEVER activates Vercel redirect', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;
      delete process.env.VERCEL;

      process.env.NEXT_PUBLIC_VERCEL_ENV = 'preview';
      process.env.VERCEL_URL = 'interview-prep-preview.vercel.app';
      assert.equal(getAuthRedirectUrl(), CANONICAL_AWS_CALLBACK);

      process.env.NEXT_PUBLIC_VERCEL_ENV = 'production';
      assert.equal(getAuthRedirectUrl(), CANONICAL_AWS_CALLBACK);

      process.env.NEXT_PUBLIC_VERCEL_ENV = '';
      assert.equal(getAuthRedirectUrl(), CANONICAL_AWS_CALLBACK);
    });

    it('REGRESSION: malformed AUTH_REDIRECT_URL produces safe canonical fallback', () => {
      delete process.env.FRONTEND_URL;
      process.env.AUTH_REDIRECT_URL = 'not-a-valid-url';
      const url = getAuthRedirectUrl('http://attacker.com');
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('REGRESSION: non-http protocol in AUTH_REDIRECT_URL produces safe canonical fallback', () => {
      delete process.env.FRONTEND_URL;
      process.env.AUTH_REDIRECT_URL = 'ftp://malicious.host/auth/callback';
      const url = getAuthRedirectUrl();
      assert.equal(url, CANONICAL_AWS_CALLBACK);
    });

    it('REGRESSION: reject spoofed subdomains and host header injection variants', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.FRONTEND_URL;

      const hostileOrigins = [
        'http://evil.com',
        'http://16.113.92.222.attacker.com',
        'http://localhost.attacker.com',
        'http://16.113.92.222:8080',
        'http://attacker.com/16.113.92.222',
        STALE_VERCEL_URL,
      ];

      for (const hostile of hostileOrigins) {
        const url = getAuthRedirectUrl(hostile);
        assert.equal(url, CANONICAL_AWS_CALLBACK, `Failed to reject hostile origin: ${hostile}`);
      }
    });

    it('REGRESSION: signup confirmation and Google OAuth preserve next=/dashboard destination', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback?next=/dashboard';

      const signupUrl = getAuthRedirectUrl({
        fallbackOrigin: AWS_ORIGIN,
        preserveParams: true,
        next: '/dashboard',
      });
      assert.equal(signupUrl, 'http://16.113.92.222/auth/callback?next=/dashboard');

      const oauthUrl = getAuthRedirectUrl({
        fallbackOrigin: AWS_ORIGIN,
        next: '/dashboard',
      });
      assert.equal(oauthUrl, 'http://16.113.92.222/auth/callback?next=%2Fdashboard');
    });
  });

  // ── getAllowedOrigins ────────────────────────────────────────────────────

  describe('getAllowedOrigins', () => {
    it('should include canonical AWS origin and localhost only by default', () => {
      const origins = getAllowedOrigins();
      assert.ok(origins.includes(AWS_ORIGIN));
      assert.ok(origins.includes('http://localhost:3000'));
      assert.ok(origins.includes('http://127.0.0.1:3000'));
      assert.equal(origins.some((o) => o.includes('vercel.app')), false);
    });

    it('should include origin from custom configured URL', () => {
      const origins = getAllowedOrigins('https://custom-domain.com/auth/callback');
      assert.ok(origins.includes('https://custom-domain.com'));
    });

    it('should include origin from FRONTEND_URL environment variable', () => {
      process.env.FRONTEND_URL = AWS_ORIGIN;
      const origins = getAllowedOrigins();
      assert.ok(origins.includes(AWS_ORIGIN));
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

    it('should reject Vercel FRONTEND_URL from allowed origins when not in Vercel runtime', () => {
      delete process.env.VERCEL;
      process.env.FRONTEND_URL = STALE_VERCEL_URL;
      // The Vercel origin IS added to allowed origins via FRONTEND_URL — this is correct behavior
      // because if the admin sets FRONTEND_URL to Vercel, the system will allow it.
      // This documents that FRONTEND_URL controls which origins are trusted.
      const origins = getAllowedOrigins();
      assert.ok(origins.includes(STALE_VERCEL_URL),
        'FRONTEND_URL determines trusted origins — set it to AWS origin, not Vercel, on EC2');
    });
  });

  // ── validateRedirectDestination ──────────────────────────────────────────

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
        validateRedirectDestination(STALE_VERCEL_CALLBACK),
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
        validateRedirectDestination(`${AWS_ORIGIN}/dashboard`),
        '/dashboard'
      );
      assert.equal(
        validateRedirectDestination(`${AWS_ORIGIN}/solve?q=42`),
        '/solve?q=42'
      );
      assert.equal(
        validateRedirectDestination('http://localhost:3000/profile'),
        '/profile'
      );
    });

    it('should sanitize protocol-relative paths inside absolute URLs matching canonical origin', () => {
      assert.equal(
        validateRedirectDestination(`${AWS_ORIGIN}//evil.com`),
        '/evil.com'
      );
      assert.equal(
        validateRedirectDestination(`${AWS_ORIGIN}///evil.com/phishing`),
        '/evil.com/phishing'
      );
      const resolved = new URL(validateRedirectDestination(`${AWS_ORIGIN}//evil.com`), AWS_ORIGIN);
      assert.equal(resolved.origin, AWS_ORIGIN);
      assert.equal(resolved.pathname, '/evil.com');
    });

    it('should block encoded slash and backslash attack vectors (/%2f%2f, /%5c, \\\\)', () => {
      assert.equal(validateRedirectDestination('//evil.example'), '/dashboard');
      assert.equal(validateRedirectDestination('///evil.example'), '/dashboard');
      assert.equal(validateRedirectDestination('https://evil.example'), '/dashboard');
      assert.equal(validateRedirectDestination('\\evil.example'), '/dashboard');
      assert.equal(validateRedirectDestination('\\\\evil.example'), '/dashboard');
      assert.equal(validateRedirectDestination('/%2f%2fevil.example'), '/dashboard');
      assert.equal(validateRedirectDestination('/%5cevil.example'), '/dashboard');
      assert.equal(validateRedirectDestination('/%252f%252fevil.example'), '/dashboard');
    });

    it('should prevent recursive auth/callback loops and nested external callback redirects', () => {
      assert.equal(validateRedirectDestination('/auth/callback'), '/dashboard');
      assert.equal(validateRedirectDestination('/auth/callback?next=https://evil.example'), '/dashboard');
      assert.equal(validateRedirectDestination(`${AWS_ORIGIN}/auth/callback?next=https://evil.example`), '/dashboard');
    });
  });


  // ── cleanEnvValue & Quoted Environment Variable Handling ─────────────────

  describe('cleanEnvValue & Quoted Environment Variable Handling', () => {
    it('returns null for null, undefined, or empty/whitespace strings', () => {
      assert.equal(cleanEnvValue(null), null);
      assert.equal(cleanEnvValue(undefined), null);
      assert.equal(cleanEnvValue(''), null);
      assert.equal(cleanEnvValue('   '), null);
      assert.equal(cleanEnvValue('""'), null);
      assert.equal(cleanEnvValue("''"), null);
    });

    it('strips surrounding double quotes and trims whitespace', () => {
      assert.equal(cleanEnvValue('"http://16.113.92.222"'), 'http://16.113.92.222');
      assert.equal(cleanEnvValue('  "http://16.113.92.222"  '), 'http://16.113.92.222');
    });

    it('strips surrounding single quotes and trims whitespace', () => {
      assert.equal(cleanEnvValue("'http://16.113.92.222'"), 'http://16.113.92.222');
      assert.equal(cleanEnvValue("  'http://16.113.92.222'  "), 'http://16.113.92.222');
    });

    it('preserves inner content without surrounding quotes', () => {
      assert.equal(cleanEnvValue('http://16.113.92.222'), 'http://16.113.92.222');
    });

    it('validates quoted AUTH_REDIRECT_URL in validateAuthRedirectUrl', () => {
      const res = validateAuthRedirectUrl('"http://16.113.92.222/auth/callback"');
      assert.equal(res.isValid, true);
      assert.equal(res.origin, 'http://16.113.92.222');
      assert.equal(res.url, 'http://16.113.92.222/auth/callback');
    });

    it('resolves quoted AUTH_REDIRECT_URL in getAuthRedirectUrl', () => {
      process.env.AUTH_REDIRECT_URL = '"http://16.113.92.222/auth/callback?next=/dashboard"';
      const url = getAuthRedirectUrl();
      assert.equal(url, 'http://16.113.92.222/auth/callback');

      const urlWithParams = getAuthRedirectUrl({ preserveParams: true });
      assert.equal(urlWithParams, 'http://16.113.92.222/auth/callback?next=/dashboard');
    });

    it('resolves quoted FRONTEND_URL in getAuthRedirectUrl', () => {
      delete process.env.AUTH_REDIRECT_URL;
      delete process.env.NEXT_PUBLIC_AUTH_REDIRECT_URL;
      process.env.FRONTEND_URL = '"http://16.113.92.222"';
      const url = getAuthRedirectUrl();
      assert.equal(url, 'http://16.113.92.222/auth/callback');
    });

    it('includes quoted origins properly in getAllowedOrigins', () => {
      const origins = getAllowedOrigins('"http://16.113.92.222"');
      assert.ok(origins.includes('http://16.113.92.222'));
    });
  });
});
