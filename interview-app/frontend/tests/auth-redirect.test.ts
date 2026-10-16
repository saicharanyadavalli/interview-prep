import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  validateAuthRedirectUrl,
  getAuthRedirectUrl,
  getAllowedOrigins,
  validateRedirectDestination,
  DEFAULT_ALLOWED_ORIGINS,
} from '../src/utils/auth-redirect.ts';

describe('Authentication Redirect Utilities', () => {
  const originalEnv = process.env.AUTH_REDIRECT_URL;

  afterEach(() => {
    if (originalEnv !== undefined) {
      process.env.AUTH_REDIRECT_URL = originalEnv;
    } else {
      delete process.env.AUTH_REDIRECT_URL;
    }
  });

  describe('validateAuthRedirectUrl', () => {
    it('should return error when AUTH_REDIRECT_URL is missing or empty', () => {
      const resNull = validateAuthRedirectUrl(null);
      assert.equal(resNull.isValid, false);
      assert.ok(resNull.error?.includes('AUTH_REDIRECT_URL environment variable is not configured'));

      const resEmpty = validateAuthRedirectUrl('   ');
      assert.equal(resEmpty.isValid, false);
      assert.ok(resEmpty.error?.includes('AUTH_REDIRECT_URL environment variable is not configured'));
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
      const res = validateAuthRedirectUrl('http://16.113.92.222/auth/callback?next=/dashboard');
      assert.equal(res.isValid, true);
      assert.equal(res.error, null);
      assert.equal(res.origin, 'http://16.113.92.222');
      assert.equal(res.url, 'http://16.113.92.222/auth/callback?next=/dashboard');
    });

    it('should accept valid Vercel HTTPS URL', () => {
      const url = 'https://interview-prep-saicharanyadavallis-projects.vercel.app/auth/callback?next=/dashboard';
      const res = validateAuthRedirectUrl(url);
      assert.equal(res.isValid, true);
      assert.equal(res.error, null);
      assert.equal(res.origin, 'https://interview-prep-saicharanyadavallis-projects.vercel.app');
      assert.equal(res.url, url);
    });

    it('should accept localhost URL for development', () => {
      const res = validateAuthRedirectUrl('http://localhost:3000/auth/callback?next=/dashboard');
      assert.equal(res.isValid, true);
      assert.equal(res.origin, 'http://localhost:3000');
    });
  });

  describe('getAuthRedirectUrl', () => {
    it('should fail with safe error if process.env.AUTH_REDIRECT_URL is unset', () => {
      delete process.env.AUTH_REDIRECT_URL;
      const res = getAuthRedirectUrl('/dashboard');
      assert.equal(res.url, null);
      assert.ok(res.error?.includes('AUTH_REDIRECT_URL environment variable is not configured'));
    });

    it('should preserve full EC2 redirect URL when already formatted', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222/auth/callback?next=/dashboard';
      const res = getAuthRedirectUrl('/dashboard');
      assert.equal(res.error, null);
      assert.equal(res.url, 'http://16.113.92.222/auth/callback?next=/dashboard');
    });

    it('should normalize base URL to include /auth/callback and next query parameter', () => {
      process.env.AUTH_REDIRECT_URL = 'http://16.113.92.222';
      const res = getAuthRedirectUrl('/dashboard');
      assert.equal(res.error, null);
      assert.equal(res.url, 'http://16.113.92.222/auth/callback?next=%2Fdashboard');
    });

    it('should handle Vercel deployment URL correctly', () => {
      process.env.AUTH_REDIRECT_URL =
        'https://interview-prep-saicharanyadavallis-projects.vercel.app/auth/callback?next=/dashboard';
      const res = getAuthRedirectUrl('/dashboard');
      assert.equal(res.error, null);
      assert.equal(
        res.url,
        'https://interview-prep-saicharanyadavallis-projects.vercel.app/auth/callback?next=/dashboard'
      );
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
