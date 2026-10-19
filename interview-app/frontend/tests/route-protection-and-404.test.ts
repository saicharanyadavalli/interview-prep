import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { NextRequest } from 'next/server.js';

import {
  proxy,
  PROTECTED_ROUTES,
  PUBLIC_ROUTES,
  isTokenActive,
  isUserAuthenticated,
  config as proxyConfig,
} from '../src/proxy.ts';
import { COGNITO_COOKIE_NAMES } from '../src/lib/cognito.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendDir = path.resolve(__dirname, '..');

// Helper to create mock JWT with custom payload
function createMockJwt(payload: Record<string, any>): string {
  const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT', kid: 'test-kid' })).toString('base64url');
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const sig = Buffer.from('mock-signature-bytes').toString('base64url');
  return `${header}.${body}.${sig}`;
}

describe('Agent B: Route Protection, Redirect Guards & 404 Specialist Suite', () => {
  // ─── Task 1: Server-Side Route Protection (frontend/src/proxy.ts) ─────────────

  describe('frontend/src/proxy.ts Configuration & Clean Architecture', () => {
    const proxyFilePath = path.join(frontendDir, 'src', 'proxy.ts');
    const proxyContent = fs.readFileSync(proxyFilePath, 'utf-8');

    it('has zero legacy Supabase dependencies in proxy.ts', () => {
      assert.doesNotMatch(proxyContent, /@supabase\/ssr/i, 'Must not import @supabase/ssr');
      assert.doesNotMatch(proxyContent, /createServerClient/i, 'Must not use createServerClient');
      assert.doesNotMatch(proxyContent, /SUPABASE_URL/i, 'Must not reference SUPABASE_URL');
      assert.doesNotMatch(proxyContent, /SUPABASE_ANON_KEY/i, 'Must not reference SUPABASE_ANON_KEY');
    });

    it('classifies PROTECTED_ROUTES according to requirements', () => {
      const expectedProtected = [
        '/dashboard',
        '/profile',
        '/progress',
        '/revisit',
        '/solve',
        '/practice',
      ];
      assert.deepEqual(PROTECTED_ROUTES, expectedProtected);
    });

    it('classifies PUBLIC_ROUTES according to requirements', () => {
      const expectedPublic = [
        '/',
        '/login',
        '/signup',
        '/courses',
        '/dsa/leetcode',
        '/questions',
        '/auth',
        '/api',
      ];
      assert.deepEqual(PUBLIC_ROUTES, expectedPublic);
    });

    it('preserves the Next.js static asset bypass matcher', () => {
      assert.ok(Array.isArray(proxyConfig.matcher));
      assert.equal(
        proxyConfig.matcher[0],
        '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)'
      );
    });
  });

  describe('JWT Expiration and Session Inspection (isTokenActive & isUserAuthenticated)', () => {
    it('returns false for null, undefined, empty, or malformed tokens', () => {
      assert.equal(isTokenActive(null), false);
      assert.equal(isTokenActive(undefined), false);
      assert.equal(isTokenActive(''), false);
      assert.equal(isTokenActive('not-a-jwt'), false);
      assert.equal(isTokenActive('only.one-part'), false);
      assert.equal(isTokenActive('part1.part2-not-json.part3'), false);
    });

    it('returns false for expired token (exp in past)', () => {
      const pastSeconds = Math.floor(Date.now() / 1000) - 3600; // 1 hour ago
      const token = createMockJwt({ sub: 'user-123', exp: pastSeconds });
      assert.equal(isTokenActive(token), false);
    });

    it('returns true for active token (exp in future)', () => {
      const futureSeconds = Math.floor(Date.now() / 1000) + 3600; // 1 hour in future
      const token = createMockJwt({ sub: 'user-123', exp: futureSeconds });
      assert.equal(isTokenActive(token), true);
    });

    it('authenticates user via ACCESS_TOKEN or ID_TOKEN cookies', () => {
      const futureSeconds = Math.floor(Date.now() / 1000) + 3600;
      const validToken = createMockJwt({ sub: 'user-123', exp: futureSeconds });

      // No cookies -> unauthenticated
      const reqNoCookies = new NextRequest('http://localhost:3000/dashboard');
      assert.equal(isUserAuthenticated(reqNoCookies), false);

      // ACCESS_TOKEN cookie present and valid
      const reqWithAccess = new NextRequest('http://localhost:3000/dashboard', {
        headers: {
          cookie: `${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=${validToken}`,
        },
      });
      assert.equal(isUserAuthenticated(reqWithAccess), true);

      // ID_TOKEN cookie present and valid
      const reqWithId = new NextRequest('http://localhost:3000/dashboard', {
        headers: {
          cookie: `${COGNITO_COOKIE_NAMES.ID_TOKEN}=${validToken}`,
        },
      });
      assert.equal(isUserAuthenticated(reqWithId), true);
    });
  });

  describe('Route Protection & Redirection Logic (proxy middleware)', () => {
    it('redirects unauthenticated user accessing protected route to /login with preserved next parameter', async () => {
      const req = new NextRequest('http://localhost:3000/solve?qnum=42&lang=python');
      const res = await proxy(req);

      assert.equal(res.status, 307);
      const location = res.headers.get('location') || '';
      assert.ok(location.includes('/login?next='));
      assert.ok(location.includes(encodeURIComponent('/solve?qnum=42&lang=python')));
    });

    it('redirects unauthenticated user accessing /dashboard to /login?next=%2Fdashboard', async () => {
      const req = new NextRequest('http://localhost:3000/dashboard');
      const res = await proxy(req);

      assert.equal(res.status, 307);
      const location = res.headers.get('location') || '';
      assert.equal(location, 'http://localhost:3000/login?next=%2Fdashboard');
    });

    it('redirects authenticated user visiting /login to /dashboard', async () => {
      const validToken = createMockJwt({
        sub: 'user-123',
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      const req = new NextRequest('http://localhost:3000/login', {
        headers: {
          cookie: `${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=${validToken}`,
        },
      });
      const res = await proxy(req);

      assert.equal(res.status, 307);
      const location = res.headers.get('location') || '';
      assert.equal(location, 'http://localhost:3000/dashboard');
    });

    it('redirects authenticated user visiting root / to /dashboard', async () => {
      const validToken = createMockJwt({
        sub: 'user-123',
        exp: Math.floor(Date.now() / 1000) + 3600,
      });

      const req = new NextRequest('http://localhost:3000/', {
        headers: {
          cookie: `${COGNITO_COOKIE_NAMES.ACCESS_TOKEN}=${validToken}`,
        },
      });
      const res = await proxy(req);

      assert.equal(res.status, 307);
      const location = res.headers.get('location') || '';
      assert.equal(location, 'http://localhost:3000/dashboard');
    });

    it('redirects /signup to /login?mode=signup for unauthenticated users', async () => {
      const req = new NextRequest('http://localhost:3000/signup');
      const res = await proxy(req);

      assert.equal(res.status, 307);
      const location = res.headers.get('location') || '';
      assert.equal(location, 'http://localhost:3000/login?mode=signup');
    });

    it('allows unauthenticated access to public routes without redirecting', async () => {
      const publicPaths = ['/questions', '/courses', '/dsa/leetcode'];

      for (const p of publicPaths) {
        const req = new NextRequest(`http://localhost:3000${p}`);
        const res = await proxy(req);
        // NextResponse.next() returns 200 (not 307 redirect)
        assert.equal(res.status, 200, `Expected public route ${p} to pass through without redirect`);
        assert.equal(res.headers.get('location'), null);
      }
    });

    it('forwards OAuth authorization code arriving at root / to /auth/callback', async () => {
      const req = new NextRequest('http://localhost:3000/?code=auth-code-12345&state=xyz');
      const res = await proxy(req);

      assert.equal(res.status, 307);
      const location = res.headers.get('location') || '';
      assert.ok(location.includes('/auth/callback'));
      assert.ok(location.includes('code=auth-code-12345'));
    });
  });

  // ─── Task 2: Client-Side Redirect Guards & Spinners ──────────────────────────

  describe('Client-Side Pages: Dashboard & Profile Guards', () => {
    it('ensures dashboard/page.tsx redirects unauthenticated users to /login?next=/dashboard', () => {
      const dashboardPath = path.join(frontendDir, 'src', 'app', 'dashboard', 'page.tsx');
      const content = fs.readFileSync(dashboardPath, 'utf-8');

      // Must import useRouter
      assert.match(content, /useRouter/);

      // Must import Spinner
      assert.match(content, /import\s*\{\s*Spinner\s*\}\s*from\s*["']@\/components\/Spinner["']/);

      // Must redirect to /login?next=/dashboard
      assert.match(
        content,
        /router\.replace\(["']\/login\?next=\/dashboard["']\)/,
        'Dashboard must execute router.replace("/login?next=/dashboard")'
      );

      // Must render clean loading spinner while authLoading or unauthenticated
      assert.match(
        content,
        /if\s*\(\s*authLoading\s*\|\|\s*!user\s*\|\|\s*!session\s*\)\s*\{[\s\S]*?<Spinner\s+text=["']Loading dashboard\.\.\.["']\s*\/>/,
        'Dashboard must render Spinner while authLoading or unauthenticated'
      );
    });

    it('ensures profile/page.tsx redirects unauthenticated users to /login?next=/profile', () => {
      const profilePath = path.join(frontendDir, 'src', 'app', 'profile', 'page.tsx');
      const content = fs.readFileSync(profilePath, 'utf-8');

      // Must import useRouter
      assert.match(content, /useRouter/);

      // Must import Spinner
      assert.match(content, /import\s*\{\s*Spinner\s*\}\s*from\s*["']@\/components\/Spinner["']/);

      // Must redirect to /login?next=/profile
      assert.match(
        content,
        /router\.replace\(["']\/login\?next=\/profile["']\)/,
        'Profile must execute router.replace("/login?next=/profile")'
      );

      // Must render Spinner while loading profile instead of empty form
      assert.match(
        content,
        /if\s*\(\s*authLoading\s*\|\|\s*!user\s*\)\s*\{[\s\S]*?<Spinner\s+text=["']Loading profile\.\.\.["']\s*\/>/,
        'Profile must render Spinner while loading profile'
      );
    });
  });

  // ─── Task 3: 404 Error Page (frontend/src/app/not-found.tsx) ──────────────────

  describe('frontend/src/app/not-found.tsx 404 Page', () => {
    const notFoundPath = path.join(frontendDir, 'src', 'app', 'not-found.tsx');

    it('exists and is a valid Next.js App Router not-found component', () => {
      assert.ok(fs.existsSync(notFoundPath), 'frontend/src/app/not-found.tsx must exist');
      const content = fs.readFileSync(notFoundPath, 'utf-8');

      // Must have default export
      assert.match(content, /export\s+default\s+function\s+NotFound\s*\(\s*\)/);
    });

    it('contains brand styling and theme tokens', () => {
      const content = fs.readFileSync(notFoundPath, 'utf-8');
      assert.ok(content.includes('var(--paper)'), 'Must use var(--paper)');
      assert.ok(content.includes('var(--ink)'), 'Must use var(--ink)');
      assert.ok(content.includes('var(--teal)'), 'Must use var(--teal)');
      assert.ok(content.includes('var(--line)'), 'Must use var(--line)');
    });

    it('renders friendly illustration or icon from lucide-react', () => {
      const content = fs.readFileSync(notFoundPath, 'utf-8');
      assert.match(content, /from\s+["']lucide-react["']/);
      assert.ok(content.includes('FileQuestion') || content.includes('HelpCircle'));
    });

    it('contains required headline and description text', () => {
      const content = fs.readFileSync(notFoundPath, 'utf-8');
      assert.ok(content.includes('404 - Page Not Found'));
      assert.ok(
        content.includes(
          'The page you are looking for might have been removed, had its name changed, or is temporarily unavailable.'
        )
      );
    });

    it('contains accessible action buttons linking to /dashboard and /questions', () => {
      const content = fs.readFileSync(notFoundPath, 'utf-8');

      // Go to Dashboard
      assert.match(
        content,
        /<Link[^>]*href=["']\/dashboard["'][^>]*>[\s\S]*?Go to Dashboard[\s\S]*?<\/Link>/
      );

      // Browse Questions
      assert.match(
        content,
        /<Link[^>]*href=["']\/questions["'][^>]*>[\s\S]*?Browse Questions[\s\S]*?<\/Link>/
      );
    });
  });
});
