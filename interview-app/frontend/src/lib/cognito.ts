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

export interface CognitoAccessTokenClaims {
  sub: string;
  client_id: string;
  token_use: 'access';
  scope?: string;
  auth_time?: number;
  iss: string;
  exp: number;
  iat: number;
  jti?: string;
  username?: string;
  'cognito:groups'?: string[];
  [key: string]: any;
}

export interface CognitoIdTokenClaims {
  sub: string;
  email?: string;
  email_verified?: boolean;
  name?: string;
  identities?: CognitoIdentityClaim[] | string;
  'cognito:username'?: string;
  'cognito:groups'?: string[];
  aud: string;
  iss: string;
  token_use: 'id';
  iat?: number;
  nbf?: number;
  exp: number;
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

export interface CognitoSignUpResult {
  userConfirmed: boolean;
  userSub: string;
  codeDeliveryDetails?: CognitoCodeDeliveryDetails;
  raw?: any;
}

export interface CognitoCodeDeliveryDetails {
  destination?: string;
  deliveryMedium?: string;
  attributeName?: string;
}

export interface CognitoAuthResult {
  accessToken: string;
  idToken: string;
  refreshToken?: string;
  expiresIn: number;
  tokenType: string;
  access_token: string;
  id_token: string;
  refresh_token?: string;
  expires_in: number;
  token_type: string;
  challengeName?: string;
  session?: string;
  raw?: any;
}

export interface VerifyIdTokenOptions {
  idToken?: string;
  userPoolId?: string;
  region?: string;
  clientId?: string;
  expectedNonce?: string;
  clockToleranceSeconds?: number;
  jwksUri?: string;
  skipSignatureVerification?: boolean;
}

interface CognitoJwkKey {
  alg: string;
  e: string;
  kid: string;
  kty: string;
  n: string;
  use?: string;
}

const jwksCache = new Map<string, { keys: CognitoJwkKey[]; fetchedAt: number }>();
const JWKS_CACHE_TTL_MS = 60 * 60 * 1000; // 1 hour

/**
 * Clears the in-memory JWKS cache (useful for tests).
 */
export function clearCognitoJwksCache(): void {
  jwksCache.clear();
}

/**
 * Base64URL decodes a string to a UTF-8 string.
 */
function base64UrlDecode(str: string): string {
  let base64 = str.replace(/-/g, '+').replace(/_/g, '/');
  while (base64.length % 4 !== 0) {
    base64 += '=';
  }
  if (typeof Buffer !== 'undefined') {
    return Buffer.from(base64, 'base64').toString('utf-8');
  }
  return decodeURIComponent(
    atob(base64)
      .split('')
      .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
      .join('')
  );
}

/**
 * Base64URL decodes a string to a Uint8Array byte array.
 */
function base64UrlToUint8Array(str: string): Uint8Array<ArrayBuffer> {
  let base64 = str.replace(/-/g, '+').replace(/_/g, '/');
  while (base64.length % 4 !== 0) {
    base64 += '=';
  }
  if (typeof Buffer !== 'undefined') {
    const buf = Buffer.from(base64, 'base64');
    const bytes = new Uint8Array(buf.length);
    bytes.set(buf);
    return bytes;
  }
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

/**
 * Helper to execute Cognito Identity Provider HTTPS API requests with application/x-amz-json-1.1
 */
async function callCognitoIdp<T = any>(
  action: string,
  payload: Record<string, any>,
  customRegion?: string
): Promise<T> {
  const config = getCognitoConfig();
  const region = customRegion || config.region || 'ap-south-2';
  const endpoint = `https://cognito-idp.${region}.amazonaws.com/`;

  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': `AWSCognitoIdentityProviderService.${action}`,
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
  });

  if (!response.ok) {
    const errBody = await response.json().catch(() => ({}));
    const rawType = errBody.__type || errBody.code || '';
    const code = rawType.split('#').pop() || 'CognitoError';
    const message =
      errBody.message ||
      errBody.Message ||
      `Cognito ${action} failed (${response.status}): ${rawType}`;
    const error = new Error(message);
    (error as any).code = code;
    (error as any).statusCode = response.status;
    (error as any).__type = rawType;
    throw error;
  }

  return (await response.json()) as T;
}

/**
 * Signs up a new user via Cognito Identity Provider SignUp API.
 * Endpoint: POST https://cognito-idp.${region}.amazonaws.com/
 * Header: X-Amz-Target: AWSCognitoIdentityProviderService.SignUp
 * Attributes: email, name, preferred_username
 */
export async function signUpWithCognito(
  email: string,
  password: string,
  username?: string,
  fullName?: string,
  options?: { clientId?: string; region?: string }
): Promise<CognitoSignUpResult> {
  const config = getCognitoConfig();
  const clientId = options?.clientId || config.clientId;
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured for sign up.');
  }

  const cleanEmail = email.trim().toLowerCase();
  const userAttributes: Array<{ Name: string; Value: string }> = [
    { Name: 'email', Value: cleanEmail },
  ];
  if (fullName && fullName.trim()) {
    userAttributes.push({ Name: 'name', Value: fullName.trim() });
  }
  if (username && username.trim()) {
    userAttributes.push({ Name: 'preferred_username', Value: username.trim().toLowerCase() });
  }

  const payload: Record<string, any> = {
    ClientId: clientId,
    Username: cleanEmail,
    Password: password,
    UserAttributes: userAttributes,
  };

  const data = await callCognitoIdp<{
    UserConfirmed?: boolean;
    UserSub?: string;
    CodeDeliveryDetails?: {
      Destination?: string;
      DeliveryMedium?: string;
      AttributeName?: string;
    };
  }>('SignUp', payload, options?.region);

  return {
    userConfirmed: Boolean(data.UserConfirmed),
    userSub: data.UserSub || '',
    codeDeliveryDetails: data.CodeDeliveryDetails
      ? {
          destination: data.CodeDeliveryDetails.Destination,
          deliveryMedium: data.CodeDeliveryDetails.DeliveryMedium,
          attributeName: data.CodeDeliveryDetails.AttributeName,
        }
      : undefined,
    raw: data,
  };
}

/**
 * Confirms user sign up with confirmation code.
 * Endpoint: POST https://cognito-idp.${region}.amazonaws.com/
 * Header: X-Amz-Target: AWSCognitoIdentityProviderService.ConfirmSignUp
 */
export async function confirmSignUpWithCognito(
  email: string,
  confirmationCode: string,
  options?: { clientId?: string; region?: string }
): Promise<{ success: boolean; raw?: any }> {
  const config = getCognitoConfig();
  const clientId = options?.clientId || config.clientId;
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured for confirm sign up.');
  }

  const payload = {
    ClientId: clientId,
    Username: email.trim().toLowerCase(),
    ConfirmationCode: confirmationCode.trim(),
  };

  const data = await callCognitoIdp('ConfirmSignUp', payload, options?.region);
  return { success: true, raw: data };
}

/**
 * Resends user confirmation code.
 * Endpoint: POST https://cognito-idp.${region}.amazonaws.com/
 * Header: X-Amz-Target: AWSCognitoIdentityProviderService.ResendConfirmationCode
 */
export async function resendConfirmationCodeWithCognito(
  email: string,
  options?: { clientId?: string; region?: string }
): Promise<{ success: boolean; codeDeliveryDetails?: CognitoCodeDeliveryDetails; raw?: any }> {
  const config = getCognitoConfig();
  const clientId = options?.clientId || config.clientId;
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured for resending confirmation code.');
  }

  const payload = {
    ClientId: clientId,
    Username: email.trim().toLowerCase(),
  };

  const data = await callCognitoIdp<{
    CodeDeliveryDetails?: {
      Destination?: string;
      DeliveryMedium?: string;
      AttributeName?: string;
    };
  }>('ResendConfirmationCode', payload, options?.region);

  return {
    success: true,
    codeDeliveryDetails: data.CodeDeliveryDetails
      ? {
          destination: data.CodeDeliveryDetails.Destination,
          deliveryMedium: data.CodeDeliveryDetails.DeliveryMedium,
          attributeName: data.CodeDeliveryDetails.AttributeName,
        }
      : undefined,
    raw: data,
  };
}

/**
 * Authenticates user via USER_PASSWORD_AUTH flow.
 * Endpoint: POST https://cognito-idp.${region}.amazonaws.com/
 * Header: X-Amz-Target: AWSCognitoIdentityProviderService.InitiateAuth
 */
export async function initiateUserPasswordAuth(
  identifier: string,
  password: string,
  options?: { clientId?: string; region?: string }
): Promise<CognitoAuthResult> {
  const config = getCognitoConfig();
  const clientId = options?.clientId || config.clientId;
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured for user authentication.');
  }

  const payload = {
    AuthFlow: 'USER_PASSWORD_AUTH',
    ClientId: clientId,
    AuthParameters: {
      USERNAME: identifier.trim(),
      PASSWORD: password,
    },
  };

  const data = await callCognitoIdp<{
    AuthenticationResult?: {
      AccessToken?: string;
      IdToken?: string;
      RefreshToken?: string;
      ExpiresIn?: number;
      TokenType?: string;
    };
    ChallengeName?: string;
    Session?: string;
  }>('InitiateAuth', payload, options?.region);

  const auth = data.AuthenticationResult || {};
  const accessToken = auth.AccessToken || '';
  const idToken = auth.IdToken || '';
  const refreshToken = auth.RefreshToken;
  const expiresIn = auth.ExpiresIn || 3600;
  const tokenType = auth.TokenType || 'Bearer';

  return {
    accessToken,
    idToken,
    refreshToken,
    expiresIn,
    tokenType,
    access_token: accessToken,
    id_token: idToken,
    refresh_token: refreshToken,
    expires_in: expiresIn,
    token_type: tokenType,
    challengeName: data.ChallengeName,
    session: data.Session,
    raw: data,
  };
}

/**
 * Initiates forgot password flow for user.
 * Endpoint: POST https://cognito-idp.${region}.amazonaws.com/
 * Header: X-Amz-Target: AWSCognitoIdentityProviderService.ForgotPassword
 */
export async function forgotPasswordWithCognito(
  email: string,
  options?: { clientId?: string; region?: string }
): Promise<{ success: boolean; codeDeliveryDetails?: CognitoCodeDeliveryDetails; raw?: any }> {
  const config = getCognitoConfig();
  const clientId = options?.clientId || config.clientId;
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured for password recovery.');
  }

  const payload = {
    ClientId: clientId,
    Username: email.trim().toLowerCase(),
  };

  const data = await callCognitoIdp<{
    CodeDeliveryDetails?: {
      Destination?: string;
      DeliveryMedium?: string;
      AttributeName?: string;
    };
  }>('ForgotPassword', payload, options?.region);

  return {
    success: true,
    codeDeliveryDetails: data.CodeDeliveryDetails
      ? {
          destination: data.CodeDeliveryDetails.Destination,
          deliveryMedium: data.CodeDeliveryDetails.DeliveryMedium,
          attributeName: data.CodeDeliveryDetails.AttributeName,
        }
      : undefined,
    raw: data,
  };
}

/**
 * Confirms forgot password with confirmation code and new password.
 * Endpoint: POST https://cognito-idp.${region}.amazonaws.com/
 * Header: X-Amz-Target: AWSCognitoIdentityProviderService.ConfirmForgotPassword
 */
export async function confirmForgotPasswordWithCognito(
  email: string,
  confirmationCode: string,
  newPassword: string,
  options?: { clientId?: string; region?: string }
): Promise<{ success: boolean; raw?: any }> {
  const config = getCognitoConfig();
  const clientId = options?.clientId || config.clientId;
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured for confirming password reset.');
  }

  const payload = {
    ClientId: clientId,
    Username: email.trim().toLowerCase(),
    ConfirmationCode: confirmationCode.trim(),
    Password: newPassword,
  };

  const data = await callCognitoIdp('ConfirmForgotPassword', payload, options?.region);
  return { success: true, raw: data };
}

/**
 * Fetches and caches JSON Web Key Set (JWKS) from Cognito User Pool.
 */
async function getCognitoJwks(
  region: string,
  userPoolId: string,
  customJwksUri?: string,
  forceRefresh: boolean = false
): Promise<CognitoJwkKey[]> {
  const jwksUrl =
    customJwksUri ||
    `https://cognito-idp.${region}.amazonaws.com/${userPoolId}/.well-known/jwks.json`;

  const cacheKey = jwksUrl;
  const now = Date.now();
  const cached = jwksCache.get(cacheKey);

  if (!forceRefresh && cached && now - cached.fetchedAt < JWKS_CACHE_TTL_MS) {
    return cached.keys;
  }

  const res = await fetch(jwksUrl, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Failed to fetch Cognito JWKS from ${jwksUrl}: HTTP ${res.status}`);
  }

  const data = await res.json();
  const keys: CognitoJwkKey[] = data?.keys || [];
  jwksCache.set(cacheKey, { keys, fetchedAt: now });
  return keys;
}

/**
 * Cryptographically verifies a Cognito ID token against the User Pool's RS256 JWKS public keys.
 * Validates:
 * 1. RS256 signature using Web Crypto API (crypto.subtle) or Node crypto
 * 2. Exact Issuer (iss) matching https://cognito-idp.${region}.amazonaws.com/${userPoolId}
 * 3. Exact Audience (aud) strictly matching configured COGNITO_CLIENT_ID
 * 4. Token use claim strictly matching token_use === "id"
 * 5. Valid time window: exp (with clock tolerance) and nbf (if present)
 * 6. Nonce parameter matching expectedNonce (if expected)
 * 7. Key rotation lookup: unknown signing keys rejected without unverified fallback outside test
 * 8. Never skips signature verification in production/staging environments
 * 9. Exceptions do not leak token strings or payload secrets
 */
export async function verifyIdTokenCryptographically(
  tokenOrOptions: string | VerifyIdTokenOptions,
  expectedNonceOrOptions?: string | VerifyIdTokenOptions
): Promise<CognitoIdTokenClaims> {
  let idToken: string;
  let options: VerifyIdTokenOptions;

  if (typeof tokenOrOptions === 'string') {
    idToken = tokenOrOptions;
    options =
      typeof expectedNonceOrOptions === 'string'
        ? { expectedNonce: expectedNonceOrOptions }
        : expectedNonceOrOptions || {};
  } else {
    options = tokenOrOptions || {};
    idToken = options.idToken || '';
  }

  if (!idToken || typeof idToken !== 'string') {
    throw new Error('Invalid ID token: token must be a non-empty string.');
  }

  const config = getCognitoConfig();
  const region = options.region || config.region || 'ap-south-2';
  const userPoolId = options.userPoolId || config.userPoolId;
  const clientId = options.clientId || config.clientId;

  if (!userPoolId) {
    throw new Error('COGNITO_USER_POOL_ID is not configured for token verification.');
  }
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured for token verification.');
  }

  const parts = idToken.split('.');
  if (parts.length !== 3) {
    throw new Error('Invalid JWT format: token must contain exactly three dot-separated components.');
  }

  const [rawHeader, rawPayload, rawSignature] = parts;

  // 1. Decode and validate header
  let header: { alg?: string; kid?: string };
  try {
    header = JSON.parse(base64UrlDecode(rawHeader));
  } catch (err: any) {
    throw new Error('Failed to decode JWT header.');
  }

  if (header.alg !== 'RS256') {
    throw new Error(`Unsupported JWT algorithm: expected RS256, received '${header.alg || 'unknown'}'`);
  }

  if (!header.kid) {
    throw new Error("Missing 'kid' in JWT header.");
  }

  // Determine environment
  const isTest =
    process.env.NODE_ENV === 'test' ||
    process.env.TESTING === '1' ||
    process.env.TESTING === 'true' ||
    process.env.npm_lifecycle_event === 'test' ||
    Boolean(process.argv && process.argv.some((arg) => arg.includes('test')));

  // NEVER allow signature verification to be skipped in production or staging environments
  const currentEnv = (process.env.NODE_ENV as string | undefined) || '';
  const isStagingOrProd =
    currentEnv === 'production' ||
    currentEnv === 'staging' ||
    process.env.APP_ENV === 'production' ||
    process.env.APP_ENV === 'staging' ||
    process.env.ENVIRONMENT === 'production' ||
    process.env.ENVIRONMENT === 'staging';

  if (options.skipSignatureVerification && isStagingOrProd) {
    throw new Error('Signature verification cannot be skipped in staging or production environments.');
  }

  const effectiveSkipSig = Boolean(options.skipSignatureVerification && isTest && !isStagingOrProd);
  if (options.skipSignatureVerification && !effectiveSkipSig) {
    throw new Error('Signature verification cannot be skipped outside isolated test environments.');
  }

  // 2. Cryptographic signature verification using Cognito public JWKS
  if (!effectiveSkipSig) {
    let matchedKey: CognitoJwkKey | undefined;
    try {
      const jwks = await getCognitoJwks(region, userPoolId, options.jwksUri);
      matchedKey = jwks.find((k) => k.kid === header.kid);

      if (!matchedKey) {
        // Retry once with cache bypass in case of key rotation
        const refreshedJwks = await getCognitoJwks(region, userPoolId, options.jwksUri, true);
        matchedKey = refreshedJwks.find((k) => k.kid === header.kid);
      }
    } catch (fetchErr: any) {
      throw new Error(`Failed to retrieve Cognito signing keys: ${fetchErr?.message || 'network error'}`);
    }

    if (!matchedKey) {
      throw new Error(`Public key for kid '${header.kid}' not found in Cognito JWKS.`);
    }

    // 3. Verify signature cryptographically
    const dataString = `${rawHeader}.${rawPayload}`;
    const sigBytes = base64UrlToUint8Array(rawSignature);

    let isSignatureValid = false;
    if (typeof crypto !== 'undefined' && crypto.subtle) {
      try {
        const cryptoKey = await crypto.subtle.importKey(
          'jwk',
          {
            kty: matchedKey.kty,
            n: matchedKey.n,
            e: matchedKey.e,
            alg: 'RS256',
            ext: true,
          },
          {
            name: 'RSASSA-PKCS1-v1_5',
            hash: { name: 'SHA-256' },
          },
          false,
          ['verify']
        );
        const encoder = new TextEncoder();
        const dataBytes = encoder.encode(dataString);
        isSignatureValid = await crypto.subtle.verify(
          'RSASSA-PKCS1-v1_5',
          cryptoKey,
          sigBytes as any,
          dataBytes
        );
      } catch (e: any) {
        throw new Error('Cryptographic signature verification failed.');
      }
    } else {
      // Node.js crypto fallback
      try {
        const nodeCrypto = await import('crypto');
        const publicKey = nodeCrypto.createPublicKey({
          key: matchedKey as any,
          format: 'jwk',
        });
        const verifier = nodeCrypto.createVerify('RSA-SHA256');
        verifier.update(dataString);
        isSignatureValid = verifier.verify(publicKey, Buffer.from(sigBytes));
      } catch (e: any) {
        throw new Error('Cryptographic signature verification failed.');
      }
    }

    if (!isSignatureValid) {
      throw new Error('Invalid token signature: cryptographic verification failed.');
    }
  }

  // 4. Decode payload
  let claims: any;
  try {
    claims = JSON.parse(base64UrlDecode(rawPayload));
  } catch (_) {
    throw new Error('Failed to decode JWT payload.');
  }

  if (!claims || typeof claims !== 'object') {
    throw new Error('Invalid JWT payload: payload is not a valid JSON object.');
  }

  // 5. Verify issuer exact match
  const expectedIssuer = `https://cognito-idp.${region}.amazonaws.com/${userPoolId}`;
  if (claims.iss !== expectedIssuer) {
    throw new Error(`Invalid token issuer: expected '${expectedIssuer}', got '${claims.iss}'`);
  }

  // 6. Verify audience strictly against configured COGNITO_CLIENT_ID
  if (!claims.aud) {
    throw new Error("Missing 'aud' claim in ID token.");
  }
  if (claims.aud !== clientId) {
    throw new Error(`Invalid token audience: expected '${clientId}', got '${claims.aud}'`);
  }

  // 7. Verify expiration (exp) and not-before (nbf)
  const now = Math.floor(Date.now() / 1000);
  const tolerance = options.clockToleranceSeconds ?? 60;

  if (typeof claims.exp !== 'number') {
    throw new Error("Missing or invalid 'exp' claim in ID token.");
  }
  if (claims.exp + tolerance < now) {
    throw new Error(`Token has expired at ${new Date(claims.exp * 1000).toISOString()}`);
  }

  if (typeof claims.nbf === 'number' && claims.nbf - tolerance > now) {
    throw new Error(`Token is not valid before ${new Date(claims.nbf * 1000).toISOString()}`);
  }

  // 8. Verify nonce if expected
  if (options.expectedNonce) {
    if (!claims.nonce) {
      throw new Error("Missing 'nonce' claim in ID token when expectedNonce was provided.");
    }
    if (claims.nonce !== options.expectedNonce) {
      throw new Error(`Nonce mismatch: expected '${options.expectedNonce}', got '${claims.nonce}'`);
    }
  }

  // 9. Verify token_use claim strictly equals "id"
  if (claims.token_use !== 'id') {
    throw new Error(`Invalid token_use claim: expected 'id', got '${claims.token_use}'`);
  }

  // Parse identities claim if stringified
  if (typeof claims.identities === 'string') {
    try {
      claims.identities = JSON.parse(claims.identities);
    } catch (_) {}
  }

  return claims as CognitoIdTokenClaims;
}

export interface VerifyAccessTokenOptions {
  accessToken?: string;
  userPoolId?: string;
  region?: string;
  clientId?: string;
  clockToleranceSeconds?: number;
  jwksUri?: string;
  skipSignatureVerification?: boolean;
}

/**
 * Cryptographically verifies a Cognito Access token against the User Pool's RS256 JWKS public keys.
 * Validates:
 * 1. RS256 signature using Web Crypto API or Node crypto
 * 2. Exact Issuer (iss) matching https://cognito-idp.${region}.amazonaws.com/${userPoolId}
 * 3. client_id claim matching COGNITO_CLIENT_ID
 * 4. Token use claim strictly matching token_use === "access"
 * 5. Expiration (exp) and not-before (nbf)
 */
export async function verifyAccessTokenCryptographically(
  tokenOrOptions: string | VerifyAccessTokenOptions
): Promise<CognitoAccessTokenClaims> {
  let accessToken: string;
  let options: VerifyAccessTokenOptions;

  if (typeof tokenOrOptions === 'string') {
    accessToken = tokenOrOptions;
    options = {};
  } else {
    options = tokenOrOptions || {};
    accessToken = options.accessToken || '';
  }

  if (!accessToken || typeof accessToken !== 'string') {
    throw new Error('Invalid access token: token must be a non-empty string.');
  }

  const config = getCognitoConfig();
  const region = options.region || config.region || 'ap-south-2';
  const userPoolId = options.userPoolId || config.userPoolId;
  const clientId = options.clientId || config.clientId;

  if (!userPoolId) {
    throw new Error('COGNITO_USER_POOL_ID is not configured for token verification.');
  }
  if (!clientId) {
    throw new Error('COGNITO_CLIENT_ID is not configured for token verification.');
  }

  const parts = accessToken.split('.');
  if (parts.length !== 3) {
    throw new Error('Invalid JWT format: token must contain exactly three dot-separated components.');
  }

  const [rawHeader, rawPayload, rawSignature] = parts;

  let header: { alg?: string; kid?: string };
  try {
    header = JSON.parse(base64UrlDecode(rawHeader));
  } catch (_) {
    throw new Error('Failed to decode JWT header.');
  }

  if (header.alg !== 'RS256') {
    throw new Error(`Unsupported JWT algorithm: expected RS256, received '${header.alg || 'unknown'}'`);
  }

  if (!header.kid) {
    throw new Error("Missing 'kid' in JWT header.");
  }

  const isTest =
    process.env.NODE_ENV === 'test' ||
    process.env.TESTING === '1' ||
    process.env.TESTING === 'true' ||
    process.env.npm_lifecycle_event === 'test' ||
    Boolean(process.argv && process.argv.some((arg) => arg.includes('test')));

  const currentEnv = (process.env.NODE_ENV as string | undefined) || '';
  const isStagingOrProd =
    currentEnv === 'production' ||
    currentEnv === 'staging' ||
    process.env.APP_ENV === 'production' ||
    process.env.APP_ENV === 'staging' ||
    process.env.ENVIRONMENT === 'production' ||
    process.env.ENVIRONMENT === 'staging';

  if (options.skipSignatureVerification && isStagingOrProd) {
    throw new Error('Signature verification cannot be skipped in staging or production environments.');
  }

  const effectiveSkipSig = Boolean(options.skipSignatureVerification && isTest && !isStagingOrProd);
  if (options.skipSignatureVerification && !effectiveSkipSig) {
    throw new Error('Signature verification cannot be skipped outside isolated test environments.');
  }

  if (!effectiveSkipSig) {
    let matchedKey: CognitoJwkKey | undefined;
    try {
      const jwks = await getCognitoJwks(region, userPoolId, options.jwksUri);
      matchedKey = jwks.find((k) => k.kid === header.kid);
      if (!matchedKey) {
        const refreshedJwks = await getCognitoJwks(region, userPoolId, options.jwksUri, true);
        matchedKey = refreshedJwks.find((k) => k.kid === header.kid);
      }
    } catch (fetchErr: any) {
      throw new Error(`Failed to retrieve Cognito signing keys: ${fetchErr?.message || 'network error'}`);
    }

    if (!matchedKey) {
      throw new Error(`Public key for kid '${header.kid}' not found in Cognito JWKS.`);
    }

    const dataString = `${rawHeader}.${rawPayload}`;
    const sigBytes = base64UrlToUint8Array(rawSignature);
    let isSignatureValid = false;

    if (typeof crypto !== 'undefined' && crypto.subtle) {
      try {
        const cryptoKey = await crypto.subtle.importKey(
          'jwk',
          {
            kty: matchedKey.kty,
            n: matchedKey.n,
            e: matchedKey.e,
            alg: 'RS256',
            ext: true,
          },
          {
            name: 'RSASSA-PKCS1-v1_5',
            hash: { name: 'SHA-256' },
          },
          false,
          ['verify']
        );
        const encoder = new TextEncoder();
        const dataBytes = encoder.encode(dataString);
        isSignatureValid = await crypto.subtle.verify(
          'RSASSA-PKCS1-v1_5',
          cryptoKey,
          sigBytes as any,
          dataBytes
        );
      } catch (_) {
        throw new Error('Cryptographic signature verification failed.');
      }
    } else {
      try {
        const nodeCrypto = await import('crypto');
        const publicKey = nodeCrypto.createPublicKey({
          key: matchedKey as any,
          format: 'jwk',
        });
        const verifier = nodeCrypto.createVerify('RSA-SHA256');
        verifier.update(dataString);
        isSignatureValid = verifier.verify(publicKey, Buffer.from(sigBytes));
      } catch (_) {
        throw new Error('Cryptographic signature verification failed.');
      }
    }

    if (!isSignatureValid) {
      throw new Error('Invalid token signature: cryptographic verification failed.');
    }
  }

  let claims: any;
  try {
    claims = JSON.parse(base64UrlDecode(rawPayload));
  } catch (_) {
    throw new Error('Failed to decode JWT payload.');
  }

  if (!claims || typeof claims !== 'object') {
    throw new Error('Invalid JWT payload: payload is not a valid JSON object.');
  }

  const expectedIssuer = `https://cognito-idp.${region}.amazonaws.com/${userPoolId}`;
  if (claims.iss !== expectedIssuer) {
    throw new Error(`Invalid token issuer: expected '${expectedIssuer}', got '${claims.iss}'`);
  }

  if (!claims.client_id) {
    throw new Error("Missing 'client_id' claim in access token.");
  }
  if (claims.client_id !== clientId) {
    throw new Error(`Invalid token client_id: expected '${clientId}', got '${claims.client_id}'`);
  }

  if (claims.token_use !== 'access') {
    throw new Error(`Invalid token_use claim: expected 'access', got '${claims.token_use}'`);
  }

  const now = Math.floor(Date.now() / 1000);
  const tolerance = options.clockToleranceSeconds ?? 60;

  if (typeof claims.exp !== 'number') {
    throw new Error("Missing or invalid 'exp' claim in access token.");
  }
  if (claims.exp + tolerance < now) {
    throw new Error(`Token has expired at ${new Date(claims.exp * 1000).toISOString()}`);
  }

  if (typeof claims.nbf === 'number' && claims.nbf - tolerance > now) {
    throw new Error(`Token is not valid before ${new Date(claims.nbf * 1000).toISOString()}`);
  }

  return claims as CognitoAccessTokenClaims;
}

export { verifyIdTokenCryptographically as verifyCognitoIdToken };

