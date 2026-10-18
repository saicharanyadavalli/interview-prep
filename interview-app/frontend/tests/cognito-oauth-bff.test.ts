import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
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
  COGNITO_COOKIE_NAMES,
} from '../src/lib/cognito.ts';
import {
  GET as bffGet,
  POST as bffPost,
  PUT as bffPut,
  DELETE as bffDelete,
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
  });
});
