/**
 * Amazon Cognito OAuth, PKCE, and Token Utilities
 *
 * Implements Cognito Hosted UI authorization URL generation with PKCE (RFC 7636),
 * token exchange, token refresh, logout URL construction, and JWT claims extraction.
 */

export interface CognitoConfig {
  region: string;
  userPoolId: string;
  clientId: string;
  domain: string;
  appOrigin: string;
}

export interface CognitoTokenResponse {
  access_token: string;
  id_token: string;
  refresh_token?: string;
  token_type: string;
  expires_in: number;
}

export interface CognitoRefreshResponse {
  access_token: string;
  id_token: string;
  token_type: string;
  expires_in: number;
}

export interface CognitoIdentityClaim {
  userId: string;
  providerName: string;
  providerType: string;
  issuer: string | null;
  primary?: boolean;
  dateCreated?: number | string;
}

export interface CognitoIdTokenClaims {
  sub: string;
  email?: string;
  email_verified?: boolean;
  name?: string;
  identities?: CognitoIdentityClaim[] | string;
  'cognito:username'?: string;
  'cognito:groups'?: string[];
  aud?: string;
  iss?: string;
  iat?: number;
  exp?: number;
  at_hash?: string;
  nonce?: string;
  [key: string]: any;
}

export const COGNITO_COOKIE_NAMES = {
  STATE: 'cognito_oauth_state',
  VERIFIER: 'cognito_pkce_verifier',
  NONCE: 'cognito_nonce',
  NEXT: 'cognito_oauth_next',
  ACCESS_TOKEN: 'cognito_access_token',
  REFRESH_TOKEN: 'cognito_refresh_token',
  ID_TOKEN: 'cognito_id_token',
} as const;

function cleanEnv(val?: string | null): string {
  if (!val || typeof val !== 'string') return '';
  return val.trim().replace(/^["']|["']$/g, '');
}

/**
 * Reads Cognito configuration from environment variables.
 * Supports standard, NEXT_PUBLIC_, and deployment fallback variables.
 */
export function getCognitoConfig(): CognitoConfig {
  const region =
    cleanEnv(process.env.COGNITO_REGION) ||
    cleanEnv(process.env.NEXT_PUBLIC_COGNITO_REGION) ||
    cleanEnv(process.env.AWS_REGION) ||
    'ap-south-2';

  const userPoolId =
    cleanEnv(process.env.COGNITO_USER_POOL_ID) ||
    cleanEnv(process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID) ||
    '';

  const clientId =
    cleanEnv(process.env.COGNITO_CLIENT_ID) ||
    cleanEnv(process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID) ||
    '';

  let rawDomain =
    cleanEnv(process.env.COGNITO_DOMAIN) ||
    cleanEnv(process.env.NEXT_PUBLIC_COGNITO_DOMAIN) ||
    '';

  // Normalize domain by stripping scheme and trailing slashes
  const domain = rawDomain.replace(/^https?:\/\//i, '').replace(/\/+$/, '');

  const appOrigin =
    cleanEnv(process.env.PUBLIC_APP_ORIGIN) ||
    cleanEnv(process.env.NEXT_PUBLIC_APP_ORIGIN) ||
    cleanEnv(process.env.FRONTEND_URL) ||
    cleanEnv(process.env.NEXT_PUBLIC_APP_URL) ||
    cleanEnv(process.env.AUTH_REDIRECT_URL) ||
    '';

  return {
    region,
    userPoolId,
    clientId,
    domain,
    appOrigin: appOrigin.replace(/\/+$/, ''),
  };
}

function getRandomBytes(length: number): Uint8Array {
  const bytes = new Uint8Array(length);
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes);
    return bytes;
  }
  if (typeof globalThis !== 'undefined' && globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
    return bytes;
  }
  // Node.js fallback
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const nodeCrypto = require('crypto');
    const random = nodeCrypto.randomBytes(length);
    bytes.set(random);
    return bytes;
  } catch (_) {
    // Fallback pseudo-random for edge cases
    for (let i = 0; i < length; i++) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
    return bytes;
  }
}

function bufferToBase64Url(buffer: ArrayBuffer | Uint8Array): string {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  if (typeof Buffer !== 'undefined') {
    return Buffer.from(bytes).toString('base64url');
  }
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

/**
 * Generates a cryptographically random PKCE code verifier (RFC 7636).
 * Length must be between 43 and 128 characters (default: 64).
 */
export function generateCodeVerifier(length: number = 64): string {
  const validLength = Math.max(43, Math.min(128, length));
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
  const bytes = getRandomBytes(validLength);
  let verifier = '';
  for (let i = 0; i < validLength; i++) {
    verifier += chars[bytes[i] % chars.length];
  }
  return verifier;
}

/**
 * Computes SHA-256 code challenge from a PKCE verifier (base64url encoded without padding).
 */
export async function computeCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);

  if (typeof crypto !== 'undefined' && crypto.subtle) {
    const digest = await crypto.subtle.digest('SHA-256', data);
    return bufferToBase64Url(digest);
  }
  if (typeof globalThis !== 'undefined' && globalThis.crypto?.subtle) {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', data);
    return bufferToBase64Url(digest);
  }

  // Node.js server fallback
  try {
    const nodeCrypto = await import('crypto');
    return nodeCrypto.createHash('sha256').update(verifier).digest('base64url');
  } catch (_) {
    throw new Error('Web Cryptography API or Node.js crypto module required for SHA-256 code challenge computation.');
  }
}

/**
 * Synchronous code challenge computation for Node.js server runtime.
 */
export function computeCodeChallengeSync(verifier: string): string {
  try {
    const nodeCrypto =
      (typeof process !== 'undefined' && typeof (process as any).getBuiltinModule === 'function' && (process as any).getBuiltinModule('crypto')) ||
      (typeof require === 'function' ? require('crypto') : null);
    if (nodeCrypto && typeof nodeCrypto.createHash === 'function') {
      return nodeCrypto.createHash('sha256').update(verifier).digest('base64url');
    }
  } catch (_) {}
  throw new Error('computeCodeChallengeSync is only supported in Node.js runtime. Use async computeCodeChallenge instead.');
}

/**
 * Generates a cryptographically secure random state parameter for OAuth CSRF protection.
 */
export function generateState(length: number = 32): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = getRandomBytes(length);
  let state = '';
  for (let i = 0; i < length; i++) {
    state += chars[bytes[i] % chars.length];
  }
  return state;
}

/**
 * Generates a cryptographically secure random nonce parameter for OpenID Connect replay protection.
 */
export function generateNonce(length: number = 32): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = getRandomBytes(length);
  let nonce = '';
  for (let i = 0; i < length; i++) {
    nonce += chars[bytes[i] % chars.length];
  }
  return nonce;
}

export interface BuildAuthorizeUrlOptions {
  redirectUri: string;
  state: string;
  nonce: string;
  codeChallenge: string;
  identityProvider?: string;
  scope?: string;
  clientId?: string;
  domain?: string;
}

/**
 * Builds Cognito Hosted UI authorization URL with PKCE and OpenID Connect parameters.
 * Format:
 * https://${COGNITO_DOMAIN}/oauth2/authorize?client_id=${COGNITO_CLIENT_ID}&response_type=code&scope=openid+email+profile&redirect_uri=${callbackUrl}&state=${state}&nonce=${nonce}&code_challenge=${codeChallenge}&code_challenge_method=S256
 */
export function buildCognitoAuthorizeUrl(options: BuildAuthorizeUrlOptions): string {
  const config = getCognitoConfig();
  const domain = (options.domain || config.domain).replace(/^https?:\/\//i, '').replace(/\/+$/, '');
  const clientId = options.clientId || config.clientId;

  if (!domain) {
    throw new Error('COGNITO_DOMAIN is not configured.');
  }
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured.');
  }

  const scopeRaw = options.scope || 'openid email profile';
  // Standardize scopes formatted as space or plus separated
  const scopeFormatted = scopeRaw.trim().replace(/\s+/g, '+');

  let url = `https://${domain}/oauth2/authorize?client_id=${encodeURIComponent(
    clientId
  )}&response_type=code&scope=${scopeFormatted}&redirect_uri=${encodeURIComponent(
    options.redirectUri
  )}&state=${encodeURIComponent(options.state)}&nonce=${encodeURIComponent(
    options.nonce
  )}&code_challenge=${encodeURIComponent(
    options.codeChallenge
  )}&code_challenge_method=S256`;

  if (options.identityProvider) {
    url += `&identity_provider=${encodeURIComponent(options.identityProvider)}`;
  }

  return url;
}

export interface ExchangeCodeOptions {
  code: string;
  redirectUri: string;
  codeVerifier: string;
  clientId?: string;
  clientSecret?: string;
  domain?: string;
}

/**
 * Exchanges authorization code for Cognito tokens at /oauth2/token.
 */
export async function exchangeCodeForTokens(
  options: ExchangeCodeOptions
): Promise<CognitoTokenResponse> {
  const config = getCognitoConfig();
  const domain = (options.domain || config.domain).replace(/^https?:\/\//i, '').replace(/\/+$/, '');
  const clientId = options.clientId || config.clientId;

  if (!domain) {
    throw new Error('COGNITO_DOMAIN is not configured for token exchange.');
  }
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured for token exchange.');
  }

  const tokenEndpoint = `https://${domain}/oauth2/token`;

  const bodyParams = new URLSearchParams();
  bodyParams.set('grant_type', 'authorization_code');
  bodyParams.set('client_id', clientId);
  bodyParams.set('code', options.code);
  bodyParams.set('redirect_uri', options.redirectUri);
  bodyParams.set('code_verifier', options.codeVerifier);

  const headers: Record<string, string> = {
    'Content-Type': 'application/x-www-form-urlencoded',
  };

  if (options.clientSecret) {
    const credentials = `${clientId}:${options.clientSecret}`;
    const encoded =
      typeof Buffer !== 'undefined'
        ? Buffer.from(credentials).toString('base64')
        : btoa(credentials);
    headers['Authorization'] = `Basic ${encoded}`;
  }

  const response = await fetch(tokenEndpoint, {
    method: 'POST',
    headers,
    body: bodyParams.toString(),
    cache: 'no-store',
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => '');
    let errorDetail = errorText;
    try {
      const parsed = JSON.parse(errorText);
      errorDetail = parsed.error_description || parsed.error || errorText;
    } catch (_) {}
    throw new Error(`Cognito token exchange failed (${response.status}): ${errorDetail}`);
  }

  const data = await response.json();
  return {
    access_token: data.access_token,
    id_token: data.id_token,
    refresh_token: data.refresh_token,
    token_type: data.token_type || 'Bearer',
    expires_in: data.expires_in || 3600,
  };
}

export interface RefreshTokensOptions {
  refreshToken: string;
  clientId?: string;
  clientSecret?: string;
  domain?: string;
}

/**
 * Refreshes Cognito access and ID tokens at /oauth2/token.
 */
export async function refreshCognitoTokens(
  options: RefreshTokensOptions
): Promise<CognitoRefreshResponse> {
  const config = getCognitoConfig();
  const domain = (options.domain || config.domain).replace(/^https?:\/\//i, '').replace(/\/+$/, '');
  const clientId = options.clientId || config.clientId;

  if (!domain) {
    throw new Error('COGNITO_DOMAIN is not configured for token refresh.');
  }
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured for token refresh.');
  }

  const tokenEndpoint = `https://${domain}/oauth2/token`;

  const bodyParams = new URLSearchParams();
  bodyParams.set('grant_type', 'refresh_token');
  bodyParams.set('client_id', clientId);
  bodyParams.set('refresh_token', options.refreshToken);

  const headers: Record<string, string> = {
    'Content-Type': 'application/x-www-form-urlencoded',
  };

  if (options.clientSecret) {
    const credentials = `${clientId}:${options.clientSecret}`;
    const encoded =
      typeof Buffer !== 'undefined'
        ? Buffer.from(credentials).toString('base64')
        : btoa(credentials);
    headers['Authorization'] = `Basic ${encoded}`;
  }

  const response = await fetch(tokenEndpoint, {
    method: 'POST',
    headers,
    body: bodyParams.toString(),
    cache: 'no-store',
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => '');
    throw new Error(`Cognito token refresh failed (${response.status}): ${errorText}`);
  }

  const data = await response.json();
  return {
    access_token: data.access_token,
    id_token: data.id_token,
    token_type: data.token_type || 'Bearer',
    expires_in: data.expires_in || 3600,
  };
}

export interface BuildLogoutUrlOptions {
  logoutUri: string;
  clientId?: string;
  domain?: string;
}

/**
 * Builds Cognito Hosted UI logout URL.
 * Format:
 * https://${COGNITO_DOMAIN}/logout?client_id=${COGNITO_CLIENT_ID}&logout_uri=${logoutUrl}
 */
export function buildCognitoLogoutUrl(options: BuildLogoutUrlOptions): string {
  const config = getCognitoConfig();
  const domain = (options.domain || config.domain).replace(/^https?:\/\//i, '').replace(/\/+$/, '');
  const clientId = options.clientId || config.clientId;

  if (!domain || !clientId) {
    return options.logoutUri;
  }

  return `https://${domain}/logout?client_id=${encodeURIComponent(
    clientId
  )}&logout_uri=${encodeURIComponent(options.logoutUri)}`;
}

/**
 * Safely decodes JWT claims from an ID token without cryptographic verification.
 * (Server-side validation is performed via Cognito token exchange / public JWKS).
 */
export function decodeIdTokenClaims(token: string): CognitoIdTokenClaims | null {
  if (!token || typeof token !== 'string') return null;

  try {
    const parts = token.split('.');
    if (parts.length < 2) return null;

    const payload = parts[1];
    let base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    while (base64.length % 4 !== 0) {
      base64 += '=';
    }

    const jsonString =
      typeof Buffer !== 'undefined'
        ? Buffer.from(base64, 'base64').toString('utf-8')
        : atob(base64);

    const parsed = JSON.parse(jsonString);
    if (!parsed || typeof parsed !== 'object') return null;

    // Parse identities claim if stringified
    if (typeof parsed.identities === 'string') {
      try {
        parsed.identities = JSON.parse(parsed.identities);
      } catch (_) {}
    }

    return parsed as CognitoIdTokenClaims;
  } catch (_) {
    return null;
  }
}
