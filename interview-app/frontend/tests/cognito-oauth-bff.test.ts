import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {
  getCognitoConfig,
  generateCodeVerifier,
  computeCodeChallenge,
  computeCodeChallengeSync,
  generateState,
  generateNonce,
  buildCognitoAuthorizeUrl,
  buildCognitoLogoutUrl,
  decodeIdTokenClaims,
  exchangeCodeForTokens,
  refreshCognitoTokens,
  verifyCognitoIdToken,
  verifyIdTokenCryptographically,
  clearCognitoJwksCache,
  confirmSignUpWithCognito,
  resendConfirmationCodeWithCognito,
  forgotPasswordWithCognito,
  confirmForgotPasswordWithCognito,
  COGNITO_COOKIE_NAMES,
} from '../src/lib/cognito.ts';
import {
  GET as bffGet,
  POST as bffPost,
  PUT as bffPut,
  DELETE as bffDelete,
  PATCH as bffPatch,
  HEAD as bffHead,
  OPTIONS as bffOptions,
} from '../src/app/api/backend/[...path]/route.ts';

describe('Amazon Cognito PKCE, OAuth & BFF Proxy Specialist Suite', () => {
  const originalEnv = { ...process.env };
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    process.env.COGNITO_REGION = 'ap-south-2';
    process.env.COGNITO_USER_POOL_ID = 'ap-south-2_MockPool123';
    process.env.COGNITO_CLIENT_ID = 'mock-client-id-abc';
    process.env.COGNITO_DOMAIN = 'auth.interview-prep.example.com';
    process.env.PUBLIC_APP_ORIGIN = 'http://16.113.92.222';
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    process.env = { ...originalEnv };
  });

  describe('Cognito Configuration Reader', () => {
    it('reads standard and sanitized environment variables correctly', () => {
      process.env.COGNITO_DOMAIN = 'https://auth-domain.auth.ap-south-2.amazoncognito.com/';
      const config = getCognitoConfig();
      assert.equal(config.region, 'ap-south-2');
      assert.equal(config.userPoolId, 'ap-south-2_MockPool123');
      assert.equal(config.clientId, 'mock-client-id-abc');
      assert.equal(config.domain, 'auth-domain.auth.ap-south-2.amazoncognito.com');
      assert.equal(config.appOrigin, 'http://16.113.92.222');
    });

    it('falls back to default ap-south-2 region when unset', () => {
      delete process.env.COGNITO_REGION;
      delete process.env.NEXT_PUBLIC_COGNITO_REGION;
      delete process.env.AWS_REGION;
      const config = getCognitoConfig();
      assert.equal(config.region, 'ap-south-2');
    });
  });

  describe('PKCE Code Verifier & Challenge Computation', () => {
    it('generates random code verifiers within RFC 7636 length bounds (43-128 chars)', () => {
      const verifierDefault = generateCodeVerifier();
      assert.equal(verifierDefault.length, 64);
      assert.match(verifierDefault, /^[A-Za-z0-9\-._~]+$/);

      const verifierMin = generateCodeVerifier(20); // Clamped to 43
      assert.equal(verifierMin.length, 43);

      const verifierMax = generateCodeVerifier(200); // Clamped to 128
      assert.equal(verifierMax.length, 128);

      const verifierCustom = generateCodeVerifier(80);
      assert.equal(verifierCustom.length, 80);
    });

    it('computes SHA-256 code challenge matching RFC 7636 Appendix B test vector', async () => {
      // RFC 7636 Appendix B Official Test Vector
      const testVerifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
      const expectedChallenge = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM';

      const asyncChallenge = await computeCodeChallenge(testVerifier);
      assert.equal(asyncChallenge, expectedChallenge);
    });
  });

  describe('State and Nonce Generators', () => {
    it('generates distinct cryptographic state tokens with high entropy', () => {
      const state1 = generateState(32);
      const state2 = generateState(32);
      assert.equal(state1.length, 32);
      assert.equal(state2.length, 32);
      assert.notEqual(state1, state2);
      assert.match(state1, /^[A-Za-z0-9]+$/);
    });

    it('generates distinct nonce tokens with high entropy', () => {
      const nonce1 = generateNonce(32);
      const nonce2 = generateNonce(32);
      assert.equal(nonce1.length, 32);
      assert.equal(nonce2.length, 32);
      assert.notEqual(nonce1, nonce2);
      assert.match(nonce1, /^[A-Za-z0-9]+$/);
    });
  });

  describe('Hosted UI Authorize & Logout URL Builders', () => {
    it('builds canonical Cognito Hosted UI authorize URL with Google identity provider and PKCE', () => {
      const url = buildCognitoAuthorizeUrl({
        redirectUri: 'http://16.113.92.222/auth/callback',
        state: 'test-state-12345',
        nonce: 'test-nonce-67890',
        codeChallenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        identityProvider: 'Google',
      });

      const parsed = new URL(url);
      assert.equal(parsed.protocol, 'https:');
      assert.equal(parsed.hostname, 'auth.interview-prep.example.com');
      assert.equal(parsed.pathname, '/oauth2/authorize');
      assert.equal(parsed.searchParams.get('client_id'), 'mock-client-id-abc');
      assert.equal(parsed.searchParams.get('response_type'), 'code');
      assert.equal(parsed.searchParams.get('scope'), 'openid email profile');
      assert.equal(parsed.searchParams.get('redirect_uri'), 'http://16.113.92.222/auth/callback');
      assert.equal(parsed.searchParams.get('state'), 'test-state-12345');
      assert.equal(parsed.searchParams.get('nonce'), 'test-nonce-67890');
      assert.equal(parsed.searchParams.get('code_challenge'), 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
      assert.equal(parsed.searchParams.get('code_challenge_method'), 'S256');
      assert.equal(parsed.searchParams.get('identity_provider'), 'Google');
    });

    it('builds canonical Cognito logout URL', () => {
      const logoutUrl = buildCognitoLogoutUrl({
        logoutUri: 'http://16.113.92.222/login',
      });

      const parsed = new URL(logoutUrl);
      assert.equal(parsed.protocol, 'https:');
      assert.equal(parsed.hostname, 'auth.interview-prep.example.com');
      assert.equal(parsed.pathname, '/logout');
      assert.equal(parsed.searchParams.get('client_id'), 'mock-client-id-abc');
      assert.equal(parsed.searchParams.get('logout_uri'), 'http://16.113.92.222/login');
    });
  });

  describe('JWT ID Token Claims Decoding', () => {
    it('decodes sub, email, name, and identities claims without external dependencies', () => {
      // Craft a mock JWT id_token payload
      const mockPayload = {
        sub: 'cognito-user-uuid-98765',
        email: 'engineer@example.com',
        email_verified: true,
        name: 'Jane Engineer',
        'cognito:username': 'google_123456789',
        identities: [
          {
            userId: 'google-sub-123456',
            providerName: 'Google',
            providerType: 'Google',
            issuer: null,
            primary: true,
            dateCreated: 1729000000,
          },
        ],
        exp: 1800000000,
      };

      const base64UrlPayload = Buffer.from(JSON.stringify(mockPayload)).toString('base64url');
      const mockJwt = `eyJhbGciOiJSUzI1NiJ9.${base64UrlPayload}.mockSignature`;

      const claims = decodeIdTokenClaims(mockJwt);
      assert.ok(claims);
      assert.equal(claims.sub, 'cognito-user-uuid-98765');
      assert.equal(claims.email, 'engineer@example.com');
      assert.equal(claims.name, 'Jane Engineer');
      assert.equal(claims['cognito:username'], 'google_123456789');
      assert.ok(Array.isArray(claims.identities));
      assert.equal(claims.identities[0].providerName, 'Google');
    });

    it('returns null safely for malformed JWT tokens', () => {
      assert.equal(decodeIdTokenClaims(''), null);
      assert.equal(decodeIdTokenClaims('invalid.jwt'), null);
      assert.equal(decodeIdTokenClaims('not-a-token'), null);
    });
  });

  describe('Cognito Token Exchange and Refresh', () => {
    it('performs authorization code exchange at /oauth2/token with application/x-www-form-urlencoded', async () => {
      let capturedUrl = '';
      let capturedMethod = '';
      let capturedHeaders: Record<string, string> = {};
      let capturedBody = '';

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        capturedUrl = String(url);
        capturedMethod = init?.method || '';
        capturedHeaders = (init?.headers as Record<string, string>) || {};
        capturedBody = String(init?.body || '');

        return new Response(
          JSON.stringify({
            access_token: 'mock-access-token-xyz',
            id_token: 'mock-id-token-abc',
            refresh_token: 'mock-refresh-token-123',
            token_type: 'Bearer',
            expires_in: 3600,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }) as any;

      const result = await exchangeCodeForTokens({
        code: 'auth-code-test-123',
        redirectUri: 'http://16.113.92.222/auth/callback',
        codeVerifier: 'code-verifier-secret-999',
      });

      assert.equal(capturedUrl, 'https://auth.interview-prep.example.com/oauth2/token');
      assert.equal(capturedMethod, 'POST');
      assert.equal(capturedHeaders['Content-Type'], 'application/x-www-form-urlencoded');

      const bodyParams = new URLSearchParams(capturedBody);
      assert.equal(bodyParams.get('grant_type'), 'authorization_code');
      assert.equal(bodyParams.get('client_id'), 'mock-client-id-abc');
      assert.equal(bodyParams.get('code'), 'auth-code-test-123');
      assert.equal(bodyParams.get('redirect_uri'), 'http://16.113.92.222/auth/callback');
      assert.equal(bodyParams.get('code_verifier'), 'code-verifier-secret-999');

      assert.equal(result.access_token, 'mock-access-token-xyz');
      assert.equal(result.id_token, 'mock-id-token-abc');
      assert.equal(result.refresh_token, 'mock-refresh-token-123');
    });

    it('refreshes token using grant_type=refresh_token', async () => {
      let capturedBody = '';

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        capturedBody = String(init?.body || '');
        return new Response(
          JSON.stringify({
            access_token: 'new-access-token',
            id_token: 'new-id-token',
            token_type: 'Bearer',
            expires_in: 3600,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }) as any;

      const result = await refreshCognitoTokens({
        refreshToken: 'mock-refresh-token-123',
      });

      const bodyParams = new URLSearchParams(capturedBody);
      assert.equal(bodyParams.get('grant_type'), 'refresh_token');
      assert.equal(bodyParams.get('refresh_token'), 'mock-refresh-token-123');
      assert.equal(result.access_token, 'new-access-token');
    });
  });

  describe('Next.js BFF Proxy (/api/backend/[...path])', () => {
    it('forwards GET request with query parameters and Authorization header to backend', async () => {
      let backendRequestedUrl = '';
      let backendAuthHeader = '';

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        backendRequestedUrl = String(url);
        const headers = init?.headers as Headers;
        backendAuthHeader = headers?.get ? headers.get('authorization') || '' : (headers as any)?.['authorization'] || '';

        return new Response(JSON.stringify({ status: 'ok', data: [1, 2, 3] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }) as any;

      const req = new Request('http://16.113.92.222/api/backend/questions/all?company=Google&difficulty=Medium', {
        method: 'GET',
        headers: {
          cookie: `${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=test-session-access-token`,
        },
      });

      const response = await bffGet(req, {
        params: Promise.resolve({ path: ['questions', 'all'] }),
      });

      assert.equal(response.status, 200);
      assert.equal(backendRequestedUrl, 'http://127.0.0.1:8000/questions/all?company=Google&difficulty=Medium');
      assert.equal(backendAuthHeader, 'Bearer test-session-access-token');

      const body = await response.json();
      assert.deepEqual(body, { status: 'ok', data: [1, 2, 3] });
    });

    it('forwards POST request body to backend and returns backend response', async () => {
      let backendMethod = '';
      let backendBody = '';

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        backendMethod = init?.method || '';
        backendBody = init?.body ? Buffer.from(init.body as any).toString('utf-8') : '';

        return new Response(JSON.stringify({ id: 'created-item-123' }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        });
      }) as any;

      const req = new Request('http://16.113.92.222/api/backend/questions/custom-folder', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          cookie: `${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=test-session-access-token`,
        },
        body: JSON.stringify({ folder_name: 'Dynamic Programming', question_id: 42 }),
      });

      const response = await bffPost(req, {
        params: Promise.resolve({ path: ['questions', 'custom-folder'] }),
      });

      assert.equal(response.status, 201);
      assert.equal(backendMethod, 'POST');
      assert.equal(JSON.parse(backendBody).folder_name, 'Dynamic Programming');
    });

    it('preserves 401 Unauthorized status from backend without crashing', async () => {
      globalThis.fetch = (async () => {
        return new Response(JSON.stringify({ detail: 'Invalid or expired token.' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        });
      }) as any;

      const req = new Request('http://16.113.92.222/api/backend/profile/me', {
        method: 'GET',
      });

      const response = await bffGet(req, {
        params: Promise.resolve({ path: ['profile', 'me'] }),
      });

      assert.equal(response.status, 401);
      const data = await response.json();
      assert.equal(data.detail, 'Invalid or expired token.');
    });

    it('handles backend connection failure gracefully with 503 Service Unavailable', async () => {
      globalThis.fetch = (async () => {
        throw new Error('connect ECONNREFUSED 127.0.0.1:8000');
      }) as any;

      const req = new Request('http://16.113.92.222/api/backend/health', {
        method: 'GET',
      });

      const response = await bffGet(req, {
        params: Promise.resolve({ path: ['health'] }),
      });

      assert.equal(response.status, 503);
      const data = await response.json();
      assert.match(data.detail, /temporarily unavailable/i);
    });

    it('strictly strips unauthenticated client Authorization header when cognito_access_token cookie is absent', async () => {
      let forwardedAuthHeader = 'NOT_SET';

      globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
        const headers = init?.headers as Headers;
        forwardedAuthHeader = headers?.get ? headers.get('authorization') || '' : (headers as any)?.['authorization'] || '';
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }) as any;

      const req = new Request('http://16.113.92.222/api/backend/test/endpoint', {
        method: 'GET',
        headers: {
          authorization: 'Bearer malicious-unauthenticated-token',
        },
      });

      const response = await bffGet(req, {
        params: Promise.resolve({ path: ['test', 'endpoint'] }),
      });

      assert.equal(response.status, 200);
      assert.equal(forwardedAuthHeader, '', 'Unauthenticated client Authorization header must be stripped');
    });

    it('never forwards sb-access-token fallback when cognito_access_token is absent', async () => {
      let forwardedAuthHeader = 'NOT_SET';

      globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
        const headers = init?.headers as Headers;
        forwardedAuthHeader = headers?.get ? headers.get('authorization') || '' : (headers as any)?.['authorization'] || '';
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }) as any;

      const req = new Request('http://16.113.92.222/api/backend/test/endpoint', {
        method: 'GET',
        headers: {
          cookie: 'sb-access-token=legacy-supabase-token-xyz',
        },
      });

      const response = await bffGet(req, {
        params: Promise.resolve({ path: ['test', 'endpoint'] }),
      });

      assert.equal(response.status, 200);
      assert.equal(forwardedAuthHeader, '', 'sb-access-token must NEVER be forwarded as Authorization');
    });

    it('forwards PUT, DELETE, PATCH, and OPTIONS requests with cognito_access_token', async () => {
      const methodsTested: string[] = [];

      globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
        methodsTested.push(init?.method || '');
        const headers = init?.headers as Headers;
        const auth = headers?.get ? headers.get('authorization') : (headers as any)?.['authorization'];
        assert.equal(auth, 'Bearer valid-cognito-access-token');
        return new Response(JSON.stringify({ success: true }), { status: 200 });
      }) as any;

      const cookieHeader = `${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=valid-cognito-access-token`;

      // PUT
      await bffPut(
        new Request('http://16.113.92.222/api/backend/resource/1', {
          method: 'PUT',
          headers: { cookie: cookieHeader, 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: 'updated' }),
        }),
        { params: Promise.resolve({ path: ['resource', '1'] }) }
      );

      // DELETE
      await bffDelete(
        new Request('http://16.113.92.222/api/backend/resource/1', {
          method: 'DELETE',
          headers: { cookie: cookieHeader },
        }),
        { params: Promise.resolve({ path: ['resource', '1'] }) }
      );

      // PATCH
      await bffPatch(
        new Request('http://16.113.92.222/api/backend/resource/1', {
          method: 'PATCH',
          headers: { cookie: cookieHeader, 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'active' }),
        }),
        { params: Promise.resolve({ path: ['resource', '1'] }) }
      );

      // OPTIONS
      await bffOptions(
        new Request('http://16.113.92.222/api/backend/resource/1', {
          method: 'OPTIONS',
          headers: { cookie: cookieHeader },
        }),
        { params: Promise.resolve({ path: ['resource', '1'] }) }
      );

      // HEAD
      methodsTested.length = 0;
      await bffHead(
        new Request('http://16.113.92.222/api/backend/resource/1', {
          method: 'HEAD',
          headers: { cookie: cookieHeader },
        }),
        { params: Promise.resolve({ path: ['resource', '1'] }) }
      );
      assert.deepEqual(methodsTested, ['HEAD']);
    });

    it('proactively refreshes access token in-flight when expiring within 30s and updates response cookies', async () => {
      const now = Math.floor(Date.now() / 1000);
      // Create JWT expiring in 15 seconds (within 30s threshold)
      const hB64 = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
      const pB64 = Buffer.from(JSON.stringify({ sub: 'user-abc', exp: now + 15 })).toString('base64url');
      const tokenExpiringSoon = `${hB64}.${pB64}.mocksig`;

      let tokenEndpointCalled = false;
      let backendAuthHeader = '';

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        const urlStr = String(url);
        if (urlStr.includes('/oauth2/token')) {
          tokenEndpointCalled = true;
          return new Response(
            JSON.stringify({
              access_token: 'refreshed-in-flight-access-token',
              id_token: 'refreshed-in-flight-id-token',
              token_type: 'Bearer',
              expires_in: 3600,
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }

        if (urlStr.includes('127.0.0.1:8000')) {
          const headers = init?.headers as Headers;
          backendAuthHeader = headers?.get ? headers.get('authorization') || '' : (headers as any)?.['authorization'] || '';
          return new Response(JSON.stringify({ status: 'ok', data: 'protected-resource' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        return new Response('Not Found', { status: 404 });
      }) as any;

      const req = new Request('http://16.113.92.222/api/backend/protected/data', {
        method: 'GET',
        headers: {
          cookie: `${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=${tokenExpiringSoon}; ${COGNITO_COOKIE_NAMES.REFRESH_TOKEN}=valid-refresh-token`,
        },
      });

      const response = await bffGet(req, {
        params: Promise.resolve({ path: ['protected', 'data'] }),
      });

      assert.equal(tokenEndpointCalled, true, 'Must call Cognito /oauth2/token to refresh token');
      assert.equal(backendAuthHeader, 'Bearer refreshed-in-flight-access-token', 'Must forward refreshed token to backend');
      assert.equal(response.status, 200);

      // Verify response Set-Cookie headers
      const setCookies = response.headers.getSetCookie ? response.headers.getSetCookie() : [response.headers.get('set-cookie') || ''];
      const setCookieStr = setCookies.join('; ');
      assert.ok(setCookieStr.includes(COGNITO_COOKIE_NAMES.ACCESS_TOKEN), 'Must set updated access token cookie');
      assert.ok(setCookieStr.includes('refreshed-in-flight-access-token'), 'Must contain new access token');
      assert.ok(setCookieStr.includes(COGNITO_COOKIE_NAMES.ID_TOKEN), 'Must set updated ID token cookie');
    });

    it('refreshes expired access token in-flight when refresh token is present', async () => {
      const now = Math.floor(Date.now() / 1000);
      // Create expired JWT (expired 100 seconds ago)
      const hB64 = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
      const pB64 = Buffer.from(JSON.stringify({ sub: 'user-abc', exp: now - 100 })).toString('base64url');
      const expiredToken = `${hB64}.${pB64}.mocksig`;

      let backendAuthHeader = '';

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        const urlStr = String(url);
        if (urlStr.includes('/oauth2/token')) {
          return new Response(
            JSON.stringify({
              access_token: 'fresh-post-expiration-token',
              id_token: 'fresh-id-token',
              token_type: 'Bearer',
              expires_in: 3600,
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }

        if (urlStr.includes('127.0.0.1:8000')) {
          const headers = init?.headers as Headers;
          backendAuthHeader = headers?.get ? headers.get('authorization') || '' : (headers as any)?.['authorization'] || '';
          return new Response(JSON.stringify({ user_id: 'user-abc' }), { status: 200 });
        }

        return new Response('Not Found', { status: 404 });
      }) as any;

      const req = new Request('http://16.113.92.222/api/backend/auth/session', {
        method: 'GET',
        headers: {
          cookie: `${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=${expiredToken}; ${COGNITO_COOKIE_NAMES.REFRESH_TOKEN}=valid-refresh-token`,
        },
      });

      const response = await bffGet(req, {
        params: Promise.resolve({ path: ['auth', 'session'] }),
      });

      assert.equal(backendAuthHeader, 'Bearer fresh-post-expiration-token');
      assert.equal(response.status, 200);
    });

    it('clears session cookies cleanly and proceeds unauthenticated to backend 401 when token refresh fails', async () => {
      const now = Math.floor(Date.now() / 1000);
      const hB64 = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
      const pB64 = Buffer.from(JSON.stringify({ sub: 'user-abc', exp: now - 100 })).toString('base64url');
      const expiredToken = `${hB64}.${pB64}.mocksig`;

      let backendAuthHeader: string | null = 'NOT_CALLED';

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        const urlStr = String(url);
        if (urlStr.includes('/oauth2/token')) {
          // Token refresh fails (e.g. refresh token revoked)
          return new Response(JSON.stringify({ error: 'invalid_grant' }), { status: 400 });
        }

        if (urlStr.includes('127.0.0.1:8000')) {
          const headers = init?.headers as Headers;
          backendAuthHeader = headers?.get ? headers.get('authorization') : (headers as any)?.['authorization'] || null;
          return new Response(JSON.stringify({ detail: 'Not authenticated' }), {
            status: 401,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        return new Response('Not Found', { status: 404 });
      }) as any;

      const req = new Request('http://16.113.92.222/api/backend/profile/me', {
        method: 'GET',
        headers: {
          cookie: `${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=${expiredToken}; ${COGNITO_COOKIE_NAMES.REFRESH_TOKEN}=revoked-refresh-token`,
        },
      });

      const response = await bffGet(req, {
        params: Promise.resolve({ path: ['profile', 'me'] }),
      });

      // Must proceed unauthenticated (NO Authorization header sent to backend)
      assert.equal(backendAuthHeader, null, 'Must proceed unauthenticated when refresh fails');
      assert.equal(response.status, 401, 'Must return 401 from backend, NOT a redirect');

      const data = await response.json();
      assert.equal(data.detail, 'Not authenticated');

      // Must cleanly clear session cookies with Max-Age=0
      const setCookies = response.headers.getSetCookie ? response.headers.getSetCookie() : [response.headers.get('set-cookie') || ''];
      const setCookieStr = setCookies.join('; ');
      assert.ok(setCookieStr.includes(`${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=`), 'Must clear access token cookie');
      assert.ok(setCookieStr.includes(`${COGNITO_COOKIE_NAMES.REFRESH_TOKEN}=`), 'Must clear refresh token cookie');
      assert.ok(setCookieStr.includes(`${COGNITO_COOKIE_NAMES.ID_TOKEN}=`), 'Must clear ID token cookie');
      assert.ok(setCookieStr.includes('Max-Age=0'), 'Must set Max-Age=0 to expire cookies');
    });

    it('does NOT trigger refresh when access token has plenty of time remaining (> 30s)', async () => {
      const now = Math.floor(Date.now() / 1000);
      const hB64 = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
      const pB64 = Buffer.from(JSON.stringify({ sub: 'user-abc', exp: now + 3600 })).toString('base64url');
      const validToken = `${hB64}.${pB64}.mocksig`;

      let tokenEndpointCalled = false;
      let backendAuthHeader = '';

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        const urlStr = String(url);
        if (urlStr.includes('/oauth2/token')) {
          tokenEndpointCalled = true;
          return new Response('{}', { status: 200 });
        }

        if (urlStr.includes('127.0.0.1:8000')) {
          const headers = init?.headers as Headers;
          backendAuthHeader = headers?.get ? headers.get('authorization') || '' : (headers as any)?.['authorization'] || '';
          return new Response(JSON.stringify({ ok: true }), { status: 200 });
        }

        return new Response('Not Found', { status: 404 });
      }) as any;

      const req = new Request('http://16.113.92.222/api/backend/resource', {
        method: 'GET',
        headers: {
          cookie: `${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=${validToken}; ${COGNITO_COOKIE_NAMES.REFRESH_TOKEN}=valid-refresh-token`,
        },
      });

      const response = await bffGet(req, {
        params: Promise.resolve({ path: ['resource'] }),
      });

      assert.equal(tokenEndpointCalled, false, 'Must NOT refresh token when not expiring soon');
      assert.equal(backendAuthHeader, `Bearer ${validToken}`, 'Must forward current token');
      assert.equal(response.status, 200);

      const setCookies = response.headers.getSetCookie ? response.headers.getSetCookie() : [];
      assert.equal(setCookies.length, 0, 'No Set-Cookie headers should be returned when token not refreshed');
    });
  });

  describe('Cryptographic ID Token Verification (JWKS RS256)', () => {
    let keyPair: { publicKey: crypto.KeyObject; privateKey: crypto.KeyObject };
    let testJwk: any;
    const testKid = 'test-kid-rs256-001';

    beforeEach(() => {
      clearCognitoJwksCache();
      keyPair = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
      testJwk = keyPair.publicKey.export({ format: 'jwk' });
      testJwk.kid = testKid;
      testJwk.alg = 'RS256';
      testJwk.use = 'sig';
    });

    function createSignedIdToken(payload: Record<string, any>, headerOverrides?: Record<string, any>): string {
      const header = { alg: 'RS256', kid: testKid, ...headerOverrides };
      const hB64 = Buffer.from(JSON.stringify(header)).toString('base64url');
      const pB64 = Buffer.from(JSON.stringify(payload)).toString('base64url');
      const data = `${hB64}.${pB64}`;
      const sign = crypto.createSign('RSA-SHA256');
      sign.update(data);
      const sig = sign.sign(keyPair.privateKey, 'base64url');
      return `${data}.${sig}`;
    }

    it('successfully verifies a valid RS256 Cognito ID token with correct claims and signature', async () => {
      globalThis.fetch = (async (url: string | URL | Request) => {
        if (String(url).includes('.well-known/jwks.json')) {
          return new Response(JSON.stringify({ keys: [testJwk] }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response('Not Found', { status: 404 });
      }) as any;

      const validPayload = {
        sub: 'user-uuid-12345',
        iss: 'https://cognito-idp.ap-south-2.amazonaws.com/ap-south-2_MockPool123',
        aud: 'mock-client-id-abc',
        exp: Math.floor(Date.now() / 1000) + 3600,
        token_use: 'id',
        nonce: 'expected-nonce-xyz',
        email: 'engineer@example.com',
      };

      const signedToken = createSignedIdToken(validPayload);
      const claims = await verifyCognitoIdToken({
        idToken: signedToken,
        expectedNonce: 'expected-nonce-xyz',
      });

      assert.equal(claims.sub, 'user-uuid-12345');
      assert.equal(claims.email, 'engineer@example.com');
      assert.equal(claims.aud, 'mock-client-id-abc');
      assert.equal(claims.nonce, 'expected-nonce-xyz');
    });

    it('rejects an ID token with tampered signature', async () => {
      globalThis.fetch = (async (url: string | URL | Request) => {
        if (String(url).includes('.well-known/jwks.json')) {
          return new Response(JSON.stringify({ keys: [testJwk] }), { status: 200 });
        }
        return new Response('Not Found', { status: 404 });
      }) as any;

      const validPayload = {
        sub: 'user-uuid-12345',
        iss: 'https://cognito-idp.ap-south-2.amazonaws.com/ap-south-2_MockPool123',
        aud: 'mock-client-id-abc',
        exp: Math.floor(Date.now() / 1000) + 3600,
        token_use: 'id',
      };

      const signedToken = createSignedIdToken(validPayload);
      const tampered = signedToken.slice(0, -6) + 'XXXXXX';

      await assert.rejects(
        async () => {
          await verifyCognitoIdToken({ idToken: tampered });
        },
        /cryptographic verification failed/i
      );
    });

    it('rejects an ID token with mismatched issuer', async () => {
      const payload = {
        sub: 'user-uuid-12345',
        iss: 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_DifferentPool',
        aud: 'mock-client-id-abc',
        exp: Math.floor(Date.now() / 1000) + 3600,
      };

      const token = createSignedIdToken(payload);
      await assert.rejects(
        async () => {
          await verifyCognitoIdToken({ idToken: token, skipSignatureVerification: true });
        },
        /Invalid token issuer/i
      );
    });

    it('rejects an ID token with mismatched audience', async () => {
      const payload = {
        sub: 'user-uuid-12345',
        iss: 'https://cognito-idp.ap-south-2.amazonaws.com/ap-south-2_MockPool123',
        aud: 'unauthorized-client-id-999',
        exp: Math.floor(Date.now() / 1000) + 3600,
      };

      const token = createSignedIdToken(payload);
      await assert.rejects(
        async () => {
          await verifyCognitoIdToken({ idToken: token, skipSignatureVerification: true });
        },
        /Invalid token audience/i
      );
    });

    it('rejects an expired ID token', async () => {
      const payload = {
        sub: 'user-uuid-12345',
        iss: 'https://cognito-idp.ap-south-2.amazonaws.com/ap-south-2_MockPool123',
        aud: 'mock-client-id-abc',
        exp: Math.floor(Date.now() / 1000) - 300,
      };

      const token = createSignedIdToken(payload);
      await assert.rejects(
        async () => {
          await verifyCognitoIdToken({ idToken: token, skipSignatureVerification: true });
        },
        /expired/i
      );
    });

    it('rejects an ID token when nonce does not match expectedNonce', async () => {
      const payload = {
        sub: 'user-uuid-12345',
        iss: 'https://cognito-idp.ap-south-2.amazonaws.com/ap-south-2_MockPool123',
        aud: 'mock-client-id-abc',
        exp: Math.floor(Date.now() / 1000) + 3600,
        nonce: 'attacker-tampered-nonce',
      };

      const token = createSignedIdToken(payload);
      await assert.rejects(
        async () => {
          await verifyCognitoIdToken({
            idToken: token,
            expectedNonce: 'legitimate-session-nonce',
            skipSignatureVerification: true,
          });
        },
        /Nonce mismatch/i
      );
    });

    it('rejects non-RS256 algorithms such as HS256', async () => {
      const hB64 = Buffer.from(JSON.stringify({ alg: 'HS256', kid: testKid })).toString('base64url');
      const pB64 = Buffer.from(JSON.stringify({ sub: '123' })).toString('base64url');
      const mockHs256Token = `${hB64}.${pB64}.fakesig`;

      await assert.rejects(
        async () => {
          await verifyCognitoIdToken({ idToken: mockHs256Token });
        },
        /expected RS256/i
      );
    });
  });

  describe('Cognito Identity Provider API Operations', () => {
    it('calls ConfirmSignUp with correct Cognito JSON-RPC target and parameters', async () => {
      let targetHeader = '';
      let requestBody: any = null;

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        targetHeader = (init?.headers as Record<string, string>)?.['X-Amz-Target'] || '';
        requestBody = JSON.parse(String(init?.body || '{}'));
        return new Response(JSON.stringify({}), { status: 200 });
      }) as any;

      const result = await confirmSignUpWithCognito('testuser@example.com', '123456');
      assert.equal(result.success, true);
      assert.equal(targetHeader, 'AWSCognitoIdentityProviderService.ConfirmSignUp');
      assert.equal(requestBody.ClientId, 'mock-client-id-abc');
      assert.equal(requestBody.Username, 'testuser@example.com');
      assert.equal(requestBody.ConfirmationCode, '123456');
    });

    it('calls ResendConfirmationCode with correct target and returns code delivery details', async () => {
      let targetHeader = '';
      let requestBody: any = null;

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        targetHeader = (init?.headers as Record<string, string>)?.['X-Amz-Target'] || '';
        requestBody = JSON.parse(String(init?.body || '{}'));
        return new Response(
          JSON.stringify({
            CodeDeliveryDetails: {
              Destination: 't***@e***.com',
              DeliveryMedium: 'EMAIL',
            },
          }),
          { status: 200 }
        );
      }) as any;

      const result = await resendConfirmationCodeWithCognito('testuser@example.com');
      assert.equal(result.success, true);
      assert.equal(targetHeader, 'AWSCognitoIdentityProviderService.ResendConfirmationCode');
      assert.equal(requestBody.Username, 'testuser@example.com');
      assert.equal(result.codeDeliveryDetails?.destination, 't***@e***.com');
    });

    it('calls ForgotPassword with correct target', async () => {
      let targetHeader = '';
      let requestBody: any = null;

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        targetHeader = (init?.headers as Record<string, string>)?.['X-Amz-Target'] || '';
        requestBody = JSON.parse(String(init?.body || '{}'));
        return new Response(
          JSON.stringify({
            CodeDeliveryDetails: { Destination: 't***@e***.com', DeliveryMedium: 'EMAIL' },
          }),
          { status: 200 }
        );
      }) as any;

      const result = await forgotPasswordWithCognito('testuser@example.com');
      assert.equal(result.success, true);
      assert.equal(targetHeader, 'AWSCognitoIdentityProviderService.ForgotPassword');
      assert.equal(requestBody.Username, 'testuser@example.com');
    });

    it('calls ConfirmForgotPassword with code and new password', async () => {
      let targetHeader = '';
      let requestBody: any = null;

      globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
        targetHeader = (init?.headers as Record<string, string>)?.['X-Amz-Target'] || '';
        requestBody = JSON.parse(String(init?.body || '{}'));
        return new Response(JSON.stringify({}), { status: 200 });
      }) as any;

      const result = await confirmForgotPasswordWithCognito(
        'testuser@example.com',
        '654321',
        'NewSecurePass123!'
      );
      assert.equal(result.success, true);
      assert.equal(targetHeader, 'AWSCognitoIdentityProviderService.ConfirmForgotPassword');
      assert.equal(requestBody.ConfirmationCode, '654321');
      assert.equal(requestBody.Password, 'NewSecurePass123!');
    });
  });

  describe('Auth Callback & BFF Security Contracts Verification', () => {
    it('verifies that Supabase is completely eliminated from auth/callback/route.ts', async () => {
      const fs = await import('node:fs/promises');
      const path = await import('node:path');
      const callbackPath = path.resolve(process.cwd(), 'src/app/auth/callback/route.ts');
      const content = await fs.readFile(callbackPath, 'utf-8');

      assert.equal(content.includes('@supabase/ssr'), false, 'Must not import @supabase/ssr');
      assert.equal(content.includes('createServerClient'), false, 'Must not reference createServerClient');
      assert.equal(content.includes('supabase.auth'), false, 'Must not call supabase.auth methods');
      assert.equal(content.includes('verifyOtp'), false, 'Must not have verifyOtp');
      assert.equal(content.includes('exchangeCodeForSession'), false, 'Must not have exchangeCodeForSession');
    });

    it('verifies that /auth/session failure redirects to /login?error=sync_failed and deletes cookies', async () => {
      const fs = await import('node:fs/promises');
      const path = await import('node:path');
      const callbackPath = path.resolve(process.cwd(), 'src/app/auth/callback/route.ts');
      const content = await fs.readFile(callbackPath, 'utf-8');

      assert.ok(content.includes('sync_failed'), 'Must redirect to sync_failed when backend sync fails');
      assert.ok(content.includes('clearTemporaryCookies'), 'Must clear temporary cookies on exit');
      assert.ok(content.includes('COGNITO_COOKIE_NAMES.ACCESS_TOKEN'), 'Must set cognito_access_token cookie');
      assert.ok(content.includes('COGNITO_COOKIE_NAMES.REFRESH_TOKEN'), 'Must set cognito_refresh_token cookie');
      assert.ok(content.includes('COGNITO_COOKIE_NAMES.ID_TOKEN'), 'Must set cognito_id_token cookie');
    });

    it('verifies that sb-access-token is completely eliminated from bff route', async () => {
      const fs = await import('node:fs/promises');
      const path = await import('node:path');
      const bffPath = path.resolve(process.cwd(), 'src/app/api/backend/[...path]/route.ts');
      const content = await fs.readFile(bffPath, 'utf-8');

      assert.equal(content.includes('sb-access-token'), false, 'Must not reference sb-access-token');
      assert.ok(content.includes("lower !== 'authorization'"), 'Must strip incoming unauthenticated authorization');
    });

    it('verifies that auth/callback/route.ts forwards both access_token and id_token to /auth/session', async () => {
      const fs = await import('node:fs/promises');
      const path = await import('node:path');
      const callbackPath = path.resolve(process.cwd(), 'src/app/auth/callback/route.ts');
      const content = await fs.readFile(callbackPath, 'utf-8');

      assert.ok(content.includes('access_token: tokens.access_token'), 'Must forward access_token');
      assert.ok(content.includes('id_token: tokens.id_token'), 'Must forward id_token');
    });

    it('verifies that getCurrentSession() extracts preferred_username first and ignores Google_ prefix', async () => {
      const fs = await import('node:fs/promises');
      const path = await import('node:path');
      const authActionsPath = path.resolve(process.cwd(), 'src/app/actions/auth.ts');
      const content = await fs.readFile(authActionsPath, 'utf-8');

      assert.ok(content.includes('verifiedClaims.preferred_username'), 'Must check preferred_username first');
      assert.ok(content.includes("startsWith('Google_')"), 'Must ignore Google_ cognito:username');
    });

    it('verifies that signup and confirmEmail pre-provision profile in RDS via /auth/provision', async () => {
      const fs = await import('node:fs/promises');
      const path = await import('node:path');
      const authActionsPath = path.resolve(process.cwd(), 'src/app/actions/auth.ts');
      const content = await fs.readFile(authActionsPath, 'utf-8');

      assert.ok(content.includes('/auth/provision'), 'Must call /auth/provision in auth actions');
    });
  });
});
