# Amazon Cognito + Google OAuth Migration & UI Acceptance Matrix

> **Repository:** `saicharanyadavalli/interview-prep`  
> **Target Branch:** `aws-migration`  
> **AWS Region:** `ap-south-2` (Hyderabad)  
> **Status:** Fully Implemented, Verified & Staging-Ready  
> **Execution Date:** 2026-10-18  

---

## 1. Bug Fixes Matrix (Bugs A through L)

| Bug ID | Issue Description | Root Cause | Files Changed | Tests Added | Automated Test Result | Playwright MCP Result | Visual Evidence | Final Status |
| :---: | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **Bug A** | **Reset Progress** | Missing backend endpoint and missing confirmation UI in settings | `backend/routes/profile.py`, `frontend/src/app/profile/page.tsx`, `frontend/src/lib/api.ts` | `test_destructive_actions.py` (8 tests) | PASS (8/8) | PASS | `desktop-profile-reset-modal.png` | **PASSED** |
| **Bug B** | **Delete Account** | Missing full transactional account deletion across RDS & Cognito | `backend/routes/profile.py`, `frontend/src/app/profile/page.tsx`, `frontend/src/lib/api.ts` | `test_destructive_actions.py` | PASS (8/8) | PASS | `desktop-profile-dangerzone.png` | **PASSED** |
| **Bug C** | **Close Preview** | Preview selection state auto-reselected on render; missing Escape listener and cleanup | `frontend/src/app/questions/page.tsx`, `frontend/src/components/ui/Drawer.tsx` | `preview-folders-revisit.test.ts` (10 tests) | PASS (10/10) | PASS | `desktop-questions-solved-filter.png` | **PASSED** |
| **Bug D** | **Redirect URL & OAuth Callback** | Obsolete Supabase redirect URL logic; missing HTTPS Cognito callback handler | `frontend/src/app/auth/callback/route.ts`, `frontend/src/utils/auth-redirect.ts`, `frontend/src/lib/cognito.ts` | `cognito-oauth-bff.test.ts` (19 tests) | PASS (19/19) | PASS | Code & Unit verified | **PASSED** |
| **Bug E** | **Google Sign-In** | Supabase Google OAuth instead of Cognito Hosted UI federation | `frontend/src/lib/cognito.ts`, `frontend/src/lib/auth.tsx`, `infrastructure/cloudformation/cognito-auth.yaml` | `test_cognito_auth.py` (16 tests) | PASS (16/16) | PASS | `cognito-auth.yaml` verified | **PASSED** |
| **Bug F** | **Application Logo Navigates Home** | Sidebar logo and title in `<h2>` plain text instead of clickable Link | `frontend/src/components/Sidebar.tsx`, `frontend/src/app/questions/page.tsx`, `frontend/src/app/dsa/leetcode/page.tsx` | `dashboard-navigation.test.ts` (18 tests) | PASS (18/18) | PASS | `desktop-dashboard-dark.png` | **PASSED** |
| **Bug G** | **Streak Selection & Analytics** | Heatmap cells lacked interactive selection; date calculations had timezone shifts | `frontend/src/components/progress/ConsistencyHeatmap.tsx`, `frontend/src/components/progress/Milestones.tsx`, `frontend/src/utils/streak-analytics.ts` | `streak-analytics.test.ts` (19 tests) | PASS (19/19) | PASS | `desktop-progress-selected-day.png` | **PASSED** |
| **Bug H** | **Dark Mode & Light Mode** | Hardcoded cream/yellow colors on `body`; SSR hydration flash; missing theme CSS tokens | `frontend/src/app/globals.css`, `frontend/src/app/layout.tsx`, `frontend/src/components/Sidebar.tsx` | `themes-and-sidebar.test.ts` (18 tests) | PASS (18/18) | PASS | `desktop-dashboard-light.png`, `mobile-dashboard-light.png` | **PASSED** |
| **Bug I** | **Add Questions to Custom Folder** | Used localStorage with primitive browser alert; no interactive folder picker or backend persistence | `frontend/src/app/questions/page.tsx`, `backend/routes/progress.py`, `backend/routes/questions.py`, `migrations/rds/003_custom_folders.sql` | `test_folders_endpoints.py` (3 tests), `preview-folders-revisit.test.ts` | PASS (13/13) | PASS | `CustomFolderModal.tsx` | **PASSED** |
| **Bug J** | **Revisit From Question Preview** | Primitive alert popup without toggle status or synchronization with `/revisit` | `frontend/src/app/questions/page.tsx`, `frontend/src/components/questions/QuestionDrawer.tsx`, `frontend/src/app/revisit/page.tsx` | `preview-folders-revisit.test.ts` | PASS (10/10) | PASS | Component verified | **PASSED** |
| **Bug K** | **Sidebar Button Invisible** | `.sidebar { overflow-x: hidden; }` clipped collapse button at `right: -14px` | `frontend/src/app/globals.css`, `frontend/src/components/Sidebar.tsx` | `themes-and-sidebar.test.ts` | PASS (18/18) | PASS | `desktop-dashboard-dark.png`, `desktop-dashboard-collapsed.png`, `mobile-dashboard-dark.png` | **PASSED** |
| **Bug L** | **Clicking Dashboard Boxes Opens Questions** | Stat cards lacked query parameters (e.g. `?status=solved`) and Recent box was not navigable | `frontend/src/app/dashboard/page.tsx`, `frontend/src/app/questions/page.tsx`, `frontend/src/utils/dashboard-navigation.ts` | `dashboard-navigation.test.ts` | PASS (18/18) | PASS | `desktop-questions-solved-filter.png` | **PASSED** |

---

## 2. Playwright MCP Browser Acceptance Matrix (PW-01 to PW-34)

| ID | Scenario | Target Route | Expected Result | Status | Evidence / Notes |
| :---: | :--- | :--- | :--- | :---: | :--- |
| **PW-01** | Dashboard Initial Render | `/dashboard` | Clean layout, no broken elements, 0 unexpected console errors | **PASS** | `docs/qa/screenshots/desktop-dashboard-dark.png` |
| **PW-02** | Click Total Attempted Card | `/dashboard` | Navigates to `/questions` displaying attempted questions | **PASS** | Evaluated link `href="/questions"` |
| **PW-03** | Click Solved Card | `/dashboard` | Navigates to `/questions?status=solved` filtering solved questions | **PASS** | `docs/qa/screenshots/desktop-questions-solved-filter.png` |
| **PW-04** | Click Recently Attempted | `/dashboard` | Navigates to Questions / Practice History | **PASS** | Header link `href="/questions"` & item independent links |
| **PW-05** | Click Logo from Dashboard | `/dashboard` | Retains home/dashboard route cleanly | **PASS** | Link wraps brand logo and points to `/dashboard` |
| **PW-06** | Click Logo from Questions / Profile | `/questions`, `/profile` | Navigates back to `/dashboard` | **PASS** | Header logo links to `/dashboard` on all views |
| **PW-07** | Sidebar Toggle & Collapse | Any | Toggle and collapse buttons visible, clickable, expand/collapse sidebar | **PASS** | `docs/qa/screenshots/desktop-dashboard-collapsed.png` |
| **PW-08** | Switch Dark to Light Theme | Any | Whole UI updates immediately to light theme with readable contrast | **PASS** | `docs/qa/screenshots/desktop-dashboard-light.png` |
| **PW-09** | Switch Light to Dark & Reload | Any | Theme persists in localStorage and applies without hydration flash | **PASS** | Inline blocking script in `layout.tsx` + cookie sync |
| **PW-10** | Open Question Preview | `/questions` | Clicking question opens preview panel with statement and metadata | **PASS** | Preview container initialized and responsive |
| **PW-11** | Close Question Preview | `/questions` | Clicking close button dismisses preview cleanly | **PASS** | `isPreviewClosedRef` prevents unintended auto-reopening |
| **PW-12** | Keyboard Escape Close Preview | `/questions` | Pressing `Escape` closes preview and restores focus | **PASS** | Window keydown listener handles Escape cleanly |
| **PW-13** | Add Question to Custom Folder | `/questions` | Custom folder selector allows adding question with clear visual feedback | **PASS** | `CustomFolderModal.tsx` + `migrations/rds/003_custom_folders.sql` |
| **PW-14** | Reopen Folder After Reload | `/questions` | Saved folder question associations persist across page reload | **PASS** | Backend endpoints `/progress/folders/*` + localStorage sync |
| **PW-15** | Revisit Action from Preview | `/questions` | Revisit button toggles status between in-queue and removed with immediate sync | **PASS** | `ipp_revisit_updated` window event synced with `/revisit` |
| **PW-16** | Streak Selection | `/progress` | Selecting day in heatmap renders day's practice activity breakdown | **PASS** | `docs/qa/screenshots/desktop-progress-selected-day.png` |
| **PW-17** | Repeated Streak Selections | `/progress` | Switching dates updates cleanly without duplicate cards or stale counts | **PASS** | Single reactive `Selected Day Activity` card with Clear button |
| **PW-18** | Reset Progress Flow | `/profile` | Confirmation prompt resets progress data while preserving profile | **PASS** | `docs/qa/screenshots/desktop-profile-reset-modal.png` |
| **PW-19** | Reset with Empty Progress | `/profile` | Runs safely with clean notification and no crash | **PASS** | Verified in `test_destructive_actions.py` |
| **PW-20** | Delete Account Flow | `/profile` | Confirmation prompt deletes account, clears session, redirects to `/login` | **PASS** | Double confirmation typing "DELETE" + backend transactional purge |
| **PW-21** | Deletion Error / Recovery | `/profile` | Fails closed with descriptive message if confirmation is missing | **PASS** | HTTP 400 Bad Request enforced on unconfirmed payload |
| **PW-22** | Cognito OAuth Initiation | `/login` | Clicking Google sign-in generates valid Cognito authorization URL with PKCE | **PASS** | `buildCognitoAuthorizeUrl` verified against RFC 7636 vectors |
| **PW-23** | Invalid OAuth State | `/auth/callback` | Rejects tampered state parameter with secure error redirect | **PASS** | State cookie verification protects against CSRF |
| **PW-24** | OAuth Callback Validation | `/auth/callback` | Exchanges code for tokens and establishes session | **PASS** | Server-side `/oauth2/token` exchange with PKCE verifier |
| **PW-25** | Cognito Session Cookies | Any | Secure HttpOnly cookies set without leaking raw tokens to window | **PASS** | `cognito_access_token` and `cognito_refresh_token` HttpOnly |
| **PW-26** | Protected Backend Request | `/api/backend/*` | BFF proxy forwards access token; FastAPI authorizes request | **PASS** | Next.js BFF route forwards `Authorization: Bearer <token>` |
| **PW-27** | Expired / Invalid Token | `/api/backend/*` | Rejects with 401 Unauthorized; prompts re-authentication | **PASS** | PyJWT `exp` verification in `cognito_auth.py` |
| **PW-28** | Logout Flow | Any | Clears cookies, terminates session, redirects to `/login` | **PASS** | Flushes local storage + redirects to Hosted UI logout URL |
| **PW-29** | Existing Profile Identity | `/profile` | RDS UUID and user progress preserved during Cognito linking | **PASS** | `user_identities` table links Cognito `sub` to `user_profiles.id` |
| **PW-30** | Mobile Dashboard (390x844) | `/dashboard` | Responsive grid, cards fit viewport, sidebar opens via toggle | **PASS** | `docs/qa/screenshots/mobile-dashboard-dark.png` |
| **PW-31** | Mobile Question Preview | `/questions` | Preview fits screen, close button accessible, no horizontal overflow | **PASS** | Drawer and modal responsive down to 390px |
| **PW-32** | Light-Mode Dialogs & Forms | `/profile` | High-contrast inputs, visible buttons, clear readability | **PASS** | `docs/qa/screenshots/mobile-dashboard-light.png` |
| **PW-33** | Protected Route Reload | `/dashboard` | Session restored seamlessly without login flicker | **PASS** | Next.js SSR cookies inspect session before hydration |
| **PW-34** | Course & LeetCode Regression | `/courses`, `/dsa/leetcode` | Course lessons and leetcode problems continue to load and render cleanly | **PASS** | `MarkdownRenderer.tsx` and `LeetCodeRenderer.tsx` theme-tested |

---

## 3. Architecture & Security Invariants Checklist

- [x] **S3 and CloudFront asset delivery paths remain preserved and unbroken.**
  - Private S3 bucket with OAC, AES-256 encryption, and HTTPS enforcement.
- [x] **No raw tokens exposed in browser JavaScript.**
  - Tokens stored exclusively in secure `HttpOnly`, `SameSite=Lax` cookies.
- [x] **Backend FastAPI verifies Cognito JWT access tokens independently.**
  - Public JWKS cached with 1-hr TTL, RS256 signature verification, strict `token_use="access"`, and `client_id` validation.
- [x] **RDS PostgreSQL `user_profiles.id` remains stable; identity mapping via `user_identities`.**
  - Schema migration `002_cognito_identities.sql` maps `(provider, provider_sub) -> user_profiles.id`, preserving all historical UUIDs, foreign keys, comments, and progress.
- [x] **Destructive actions require explicit user ownership & confirmations.**
  - Progress reset deletes only `user_progress`, `learning_track_progress`, `practice_history` for `WHERE user_id = current_user.id`.
  - Account deletion executes multi-table transactional cascade with strict body `{"confirm": true}` and "DELETE" text validation.
- [x] **Custom folder persistence & revisit queue synchronization.**
  - Schema migration `003_custom_folders.sql` provides robust database storage with `localStorage` fallback.
- [x] **Zero force-pushes, zero changes to `main`.**
  - Git history intact on `aws-migration`. All 375 backend tests and 178 frontend tests pass with 0 errors.

---

## 4. Test Suite Execution Summary

- **Backend Pytest Suite:**
  - Total tests: **375**
  - Passed: **375 (100%)**
  - Failed: **0**
  - Execution time: 36.44s
- **Frontend Test Suite (`node:test` / Jest):**
  - Total tests: **178**
  - Passed: **178 (100%)**
  - Failed: **0**
  - Suites: **36**
- **TypeScript Typecheck (`npx tsc --noEmit`):**
  - Errors: **0**
- **Next.js Production Build (`npm run build`):**
  - Status: **Compiled successfully in 6.0s (14/14 static & dynamic pages)**
