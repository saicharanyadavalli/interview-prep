# Security Audit Remediation Plan

**Review date:** 2026-10-28  
**Scope:** current feature worktree, plus `main` and `aws-migration` refs  
**Review mode:** source-first. No application code, tests, builds, migrations, containers, or live services were run.

## Executive summary

The highest-priority source issue is an unauthenticated Cognito profile-provisioning path that can associate a new Cognito subject with an existing profile by caller-supplied email. A separately verified source trace shows the subject is later resolved to that profile. Fix this before deploying either AWS branch. The path still needs a sandboxed reproduction and confirmation that deployed ingress exposes it.

The `main` ref has three separate source leads: a test identity returned when `DISABLE_AUTH=true` without an observed production startup guard; an assistant endpoint configured for 5000 requests per minute despite documenting 5 per minute and 20 per hour; and an unauthenticated username lookup that returns the associated email. The first two need deployment/configuration confirmation. `aws-migration` and the active AWS branch do not share those exact implementations.

The active AWS backend also has a cookie-authenticated direct-request rate-limit identity mismatch if deployment exposes FastAPI directly; the frontend BFF normally injects Bearer. The active AWS frontend also has two source-level browser leads: a same-site cross-origin request may reach a session-authenticated BFF mutation without exact-Origin/CSRF validation, and imported LeetCode complexity fields reach unsanitized HTML sinks on the question detail page. These browser-side leads depend on attacker control of a relevant origin or configured source branch and need sandboxed validation.

This is not a completed formal audit. Required validators cannot safely read files on the current Windows runtime because no-follow and nonblocking input support is unavailable. A fresh coverage critic must still review the corrected 38-unit ledger after the final artifact edits. See the external run directory's report for the exact limits and candidate register.

## Prioritized work queue

Priority here is remediation order, not a formal vulnerability severity rating. All entries remain source candidates until the validation gates below are satisfied.

### P1 - Remove unauthenticated identity linking before AWS deployment

**Branches:** `feature/leetcode-sync-pipeline-and-hardening`, `aws-migration`  
**Evidence:** `interview-app/backend/routes/auth.py:686-764`; `interview-app/frontend/src/app/api/backend/[...path]/route.ts:193-203,266-286,337-343`; `interview-app/infrastructure/cloudformation/cognito-auth.yaml:134,185`; `interview-app/migrations/rds/002_cognito_identities.sql:11-28`; auth resolution in `interview-app/backend/routes/auth.py:80-104,376-427`.

The public `/auth/provision` handler accepts email and Cognito subject from the request body, and the public BFF forwards it without requiring a session. If the email identifies an existing profile, the handler can attach the supplied new subject to that profile. Later token resolution trusts the subject mapping. A fresh independent source verifier confirmed the path. The trigger conditions are a known victim email, a new Cognito identity not already mapped, and a reachable provision route before the normal signup flow maps the caller's own subject.

**Fix:** create or link identities only after verifying a Cognito access or ID token server-side. Derive `sub` and email from verified claims; link an existing profile only after verifying the email claim and ensuring the identity is not already bound to a different profile. Remove caller control over `user_id` and do not update an existing profile's username/name based only on email. Add database constraints that match the intended one-subject-per-profile model.

**Acceptance:** a dummy attacker identity cannot map itself to a victim profile by supplying the victim email or profile ID; valid signup still creates and links the caller's own profile; existing mappings cannot be reassigned.

**Validation gate:** run a bounded dummy-profile reproduction in an approved OS sandbox and confirm production ingress/middleware does not alter route reachability. No such run was possible during this audit.

**Parallel workstream A:** AWS identity and signup. Own auth route, identity migration, Cognito signup/provision action, and focused tests. Keep AWS branch changes coordinated because the relevant files are currently identical on both refs.

### P1 - Fail closed on `DISABLE_AUTH` in `main`

**Branch:** `main`  
**Evidence:** `interview-app/backend/routes/auth.py:28-35` on `main`; review `backend/main.py` startup path for the missing production guard.

When the flag is true, the helper returns a fixed test identity. Source does not establish whether any deployed environment sets it. On current AWS source the dependency includes a production/staging check, so do not apply this finding to those refs without new evidence.

**Fix:** reject this setting at startup in every production-like environment and keep an invariant check in the auth helper. Prefer an explicitly local-only mode that cannot be enabled by production configuration.

**Acceptance:** production/staging cannot start with auth disabled; with auth enabled, protected routes reject missing, malformed, and invalid credentials.

**Parallel workstream B:** `main` auth and configuration only.

### P1 - Restore the assistant's intended Gemini limits on `main`

**Branch:** `main`  
**Evidence:** `interview-app/backend/routes/assistant.py:1-6,24,55`; `interview-app/backend/limiter.py:31-35,59-63`.

The handler calls the metered Gemini service, but the route allows 5000 requests per minute while comments describe 5 per minute and 20 per hour. The default limiter storage is process-local memory unless configured otherwise. Actual provider billing, account limits, deployed storage, and any upstream throttling were not observed.

**Fix:** apply the reviewed per-user burst and hourly limits (or a deliberately approved replacement), ensure the key uses verified identity, configure shared storage for multi-worker deployments, and alert or fail safely when shared storage is unavailable. Add a provider-side spend/token cap if supported.

**Acceptance:** burst and hourly limits hold across production workers and match the written budget; storage failure has a documented, observable behavior.

**Parallel workstream C:** `main` assistant and rate limiting.

### P2 - Align cookie authentication with per-user rate-limit identity on AWS

**Branches:** active AWS feature and `aws-migration`  
**Evidence:** `interview-app/backend/routes/auth.py:396-406`; `interview-app/backend/middleware/rate_limit_middleware.py:26-56`; `interview-app/backend/limiter.py:616-634`; avatar route limits in `interview-app/backend/routes/profile.py:254-256`; configurable direct FastAPI target in `interview-app/infrastructure/cloudformation/alb-staging.yaml:55-60,163-194`.

The auth dependency accepts `cognito_access_token` from cookies, but rate-limit middleware derives its user key only from an Authorization Bearer header. A cookie-authenticated FastAPI request without Bearer therefore falls back to an IP key. The normal Next.js BFF adds Bearer, which avoids the mismatch through that path. The ALB template allows direct forwarding to port 8000, but the deployed target port and listener path are unknown.

**Fix:** derive the rate-limit principal from the same verified Cognito claims used by authentication, or ensure FastAPI is reachable only through the BFF path that injects Bearer. Avoid treating untrusted forwarded IP values as an equivalent principal key.

**Acceptance:** the same dummy user receives one consistent user-scoped bucket for cookie and Bearer requests; requests cannot reset limits by changing client IP; direct FastAPI access is blocked if the BFF is the only intended ingress.

**Validation gate:** compare cookie and Bearer identities in an approved OS sandbox, then have the owner confirm the deployed ALB target port and whether direct FastAPI requests are reachable.

### P2 - Remove email disclosure from `main` username lookup

**Branch:** `main`  
**Evidence:** `interview-app/backend/routes/auth.py:105-117` on `main`.

The unauthenticated endpoint returns `email` and `exists=true` from the username lookup RPC. The RPC implementation is not in this repository, so the result shape was not independently verified; the route code explicitly returns the field when supplied.

**Fix:** remove the endpoint or return a uniform response that does not reveal email or account existence. Use the identity provider's recovery flow for account recovery.

**Acceptance:** anonymous requests cannot infer registered status from response body, status, or materially different behavior; recovery still works for legitimate users.

### P2 - Reduce main Supabase signup email enumeration

**Branch:** `main`  
**Evidence:** `interview-app/frontend/src/app/actions/auth.ts:50,86,99-105`.

The public signup action maps duplicate-email provider outcomes to an account-exists response. This can disclose account state if Supabase returns those outcomes as expected. Provider behavior was not run against a dummy account.

**Fix:** use the same public response for new and existing addresses; send account-specific instructions only through the verified email flow.

**Validation gate:** compare dummy registered and unregistered addresses against an isolated Supabase fixture.

### P2 - Use a canonical auth callback origin on main

**Branch:** `main`  
**Evidence:** `interview-app/frontend/src/app/actions/auth.ts:62,77`; `interview-app/frontend/src/app/auth/callback/route.ts:25-45,58-94`.

When explicit origin configuration is absent, signup and callback logic can derive an origin from forwarded host/protocol headers. Whether trusted ingress overwrites them, the identity provider allowlists the derived host, and the resulting redirect creates an impact are deployment questions.

**Fix:** use a configured canonical origin for auth callbacks; accept forwarded host values only from trusted ingress and validate against an explicit allowlist.

**Validation gate:** owner verifies proxy header behavior and identity-provider redirect allowlist, followed by a synthetic-header callback fixture in an approved sandbox.
### P2 - Bind state-changing BFF requests to the exact origin

**Branch:** `feature/leetcode-sync-pipeline-and-hardening`  
**Evidence:** `interview-app/frontend/src/app/auth/callback/route.ts:203-224`; `interview-app/frontend/src/app/api/backend/[...path]/route.ts:193-203,266-286,337-343`; avatar mutation at `interview-app/backend/routes/profile.py:254-284,329-363`.

The session cookie is `SameSite=Lax`, and the BFF forwards mutating methods with the validated session token. Source review found no exact-Origin or CSRF-token check before forwarding. A malicious page on a same-site sibling origin may be treated as same-site by the browser, but attacker control of a sibling origin and actual deployment/browser behavior are unknown. This is a validation lead, not a proven exploit.

**Fix:** validate the `Origin` against a strict configured allowlist for every state-changing request at the BFF, or require a cryptographically random CSRF token bound to the session. Consider also validating `Sec-Fetch-Site` as defense in depth, not as the only control.

**Acceptance:** cross-origin and same-site sibling-origin form submissions cannot cause authenticated changes; same-origin app requests continue to work.

**Validation gate:** browser reproduction with a dummy session from a controlled sibling origin in an approved sandbox; confirm whether any sibling host is attacker-controllable in the deployed domain.

**Parallel workstream D:** BFF CSRF and browser auth request binding.

### P2 - Escape stored complexity values at the LeetCode detail sink

**Branch:** feature/leetcode-sync-pipeline-and-hardening  
**Evidence:** `interview-app/backend/workers/leetcode_sync_worker.py:406-430,454-475,569-592`; `interview-app/backend/services/leetcode_parser.py:312-324,375-403,443-470`; `interview-app/backend/services/leetcode_sync_service.py:301-325`; `interview-app/backend/routes/leetcode.py:208-230`; `interview-app/frontend/src/components/LeetCodeRenderer.tsx:36-38,63-85`; `interview-app/frontend/src/app/dsa/leetcode/[qnum]/page.tsx:268-290`.

The sync pipeline parses tracked Markdown from a configured repository and stores time/space complexity strings. The public approaches API returns those values. The formatter interpolates them into HTML and the detail page inserts that markup directly for both complexity fields, outside the DOMPurify path. Description and explanation content uses DOMPurify. The list page has an HTML preview sink, but the current list API omits `description_md`, so synced descriptions do not reach that sink in the reviewed path. The webhook verifies HMAC and source repo/branch; an attacker must be able to land content on the configured source branch or compromise an actor/credential that can.

**Fix:** render complexity values as escaped React text, or sanitize formatted output immediately before insertion. Also validate parsed values against a narrow text/math grammar. Keep Markdown and HTML sanitizer coverage for the separate description renderer.

**Acceptance:** a benign HTML fixture in both time and space complexity cannot create active DOM nodes; normal complexity and math formatting still render correctly.

**Validation gate:** use dummy content in an approved browser sandbox; confirm source repository, branch protection and contributor controls. No local reproduction was run during this audit.

**Parallel workstream E:** LeetCode content ingestion and rendering.
### P2 - Partition in-flight API requests by authenticated account

**Branches:** `main`, `feature/leetcode-sync-pipeline-and-hardening`  
**Evidence:** `interview-app/frontend/src/lib/api.ts:140-159` on the active branch and `:178-216` on main; signout cleanup at active `interview-app/frontend/src/lib/auth.tsx:404-417` and main `:301-312`; user-specific dashboard requests at active `dashboard/page.tsx:47-78` and main `:48-81`.

Both versions deduplicate pending GET requests by URL only, before resolving the new caller's access token. The pending map is not cleared on signout. If account A has a user-scoped request still in flight while account B requests the same URL in the same browser profile, B may receive A's promise result and display A's progress, revisit, profile or other user-specific data. Server authorization remains in place; the candidate is a browser-side response reuse across an account switch.

**Fix:** include a stable authenticated principal/session generation in the pending-request key, or cancel and clear all user-scoped requests on signout and identity change. Do not reuse a response started under a previous account.

**Acceptance:** hold a user-specific GET for dummy account A, switch to dummy account B, request the same URL, and verify only B's own response is rendered.

**Validation gate:** reproduce the timing overlap with two dummy sessions in an approved browser sandbox. No runtime reproduction was performed in this audit.

**Parallel workstream L:** shared API request lifecycle on both branches; keep the branch changes small and consistent.

### P2 - Make active AWS signup responses uniform

**Branch:** `feature/leetcode-sync-pipeline-and-hardening`  
**Evidence:** `interview-app/frontend/src/app/actions/auth.ts:446-481,518`.

The public signup action maps Cognito's duplicate-username result to an email-specific account-exists response. This may reveal whether an email is registered, depending on Cognito behavior.

**Fix:** return the same public message for new and existing addresses; send account-specific next steps only through the verified email channel.

**Validation gate:** compare registered and unregistered dummy accounts against an isolated Cognito fixture.
### P3 - Scope local custom folders to the current account

**Branches:** active feature and `aws-migration`  
**Evidence:** `interview-app/frontend/src/app/questions/page.tsx:354-376,979-998,1070-1080`; `interview-app/frontend/src/components/questions/QuestionDrawer.tsx:13,34-56,117-162,238-270`; `interview-app/frontend/src/lib/auth.tsx:404-424`; user-specific server APIs in `interview-app/frontend/src/lib/api.ts:402-417`.

The question page and QuestionDrawer both read and write the shared `questionsCustomFolders_v2` key before loading server folders for the current user. They retain it when the server response is empty or fails. Signout clears the older `questionsCustomFolderV1` key, not v2. If two accounts use the same browser profile and the second account has no server folders, the first account's folder names and question numbers may remain visible. This is a privacy lead; account-switch behavior was not exercised.

**Fix:** key the local cache by authenticated user ID, or clear it when the user changes and whenever the server returns an empty list.

**Acceptance:** sign-out/sign-in between two dummy accounts never displays the previous account's folder metadata.

**Validation gate:** reproduce with two dummy accounts in an approved browser sandbox.
### P2 - Limit GitHub Actions authority for contributor-controlled builds

**Branch:** active feature branch and any branch carrying `.github/workflows/deploy.yml`  
**Evidence:** `.github/workflows/deploy.yml` build job checks out pull-request code and installs dependencies; `actions/checkout@v4` keeps credentials by default unless disabled; workflow does not declare job-level `permissions` in the reviewed file.

Whether the token has useful write permissions, whether the token is available to install lifecycle scripts, and the repository's fork/approval settings are externally controlled. Treat this as a configuration-sensitive supply-chain lead.

**Fix:** declare least-privilege workflow/job permissions, set `persist-credentials: false` on PR checkout, separate untrusted PR validation from privileged publishing/deploy jobs, and pin third-party actions to reviewed immutable commit SHAs. Do not provide deployment secrets or OIDC authority to PR jobs.

**Acceptance:** fork and same-repository PR code cannot obtain write, package-publish, deploy, or cloud credentials; protected deployment only runs after trusted branch and environment approval.

**Validation gate:** owner confirms effective Actions settings, fork PR token policy, branch protection, environment approvals, and package lifecycle behavior.

**Parallel workstream F:** GitHub Actions and release trust.

### P2 - Reduce login account-state disclosure on AWS branches

**Branches:** `aws-migration`, active feature branch  
**Evidence:** `interview-app/backend/routes/auth.py:494-575` on the AWS source refs.

The login handler returns a distinct 403 with `needs_confirmation=true` for unconfirmed accounts and a 401 for invalid credentials. The difference can expose account state. Per-IP/per-user limiter behavior and product requirements were not exercised.

**Fix:** return an externally uniform login response for unconfirmed and invalid accounts, and move confirmation guidance to a flow that does not disclose account state. Preserve recovery for legitimate users.

**Acceptance:** anonymous callers cannot distinguish unconfirmed from nonexistent accounts by response; confirmed users can still complete recovery.

**Parallel workstream G:** AWS login privacy and frontend confirmation UX.

## Hardening and owner validation items

- **ALB/TLS:** `alb-staging.yaml` has public HTTP and HTTPS listeners, HTTP forwards to an HTTP target, and HTTPS is conditional on a certificate. Nginx redirects ordinary HTTP, but `/health` is exempt. Verify the actual target port, certificate, DNS, redirect behavior, and health path before release. Implement an ALB redirect and require certificates in production if deployment supports it.
- **ElastiCache ACL:** `elasticache.yaml` restricts ingress to the app security group and enables encryption for node-based cache, but the serverless user grants `~* +@all`. Review the application's actual Redis command use and reduce ACL privileges if feasible.
- **Avatar request buffering:** backend upload and BFF both read the full body before enforcing the avatar cap. Nginx limits bodies to 25 MiB and the route limits per user, so shared availability impact was not established. Enforce consistent early limits and bounded streaming as routine hardening.
- **Environment-file ignore rules:** the `main` root `.gitignore` does not cover every `.env.*` filename, though the frontend-specific ignore covers `.env*`; add a generic root rule while keeping `.env.example` exceptions. `aws-migration` and active feature root rules already ignore `.env.*`. No tracked secret was established and no actual `.env` file was read.
- **Avatar URL rendering:** `UserAvatar` renders profile-provided HTTP(S) and `data:image` sources as images. No cross-user avatar display or HTML execution was established; consider proxying/allowlisting remote sources to reduce tracking and privacy leakage.
- **Profile cache:** on `main`, reject legacy cached profile values without a user ID when an expected user ID is supplied. Current writes include the ID and signout clears the cache, so this remains hardening.
- **Runtime configuration:** verify `DISABLE_AUTH`, public origins, cookie Secure flags, rate-limit storage, Cognito settings, callback allowlists, and cloud route exposure without exposing secret values.

## Branch-aware parallel implementation map

Each workstream should use its own worktree, record the exact base commit, edit only its owned files, add focused tests, and report test commands/results. Do not combine `main`-only fixes with AWS identity changes.

| Workstream | Base ref | Owned scope | Priority |
|---|---|---|---|
| A - AWS identity linking | active feature and `aws-migration` | `backend/routes/auth.py`, identity migration, Cognito signup/provision flow, identity tests | P1 |
| B - Main auth guard | `main` | auth helper, startup/config validation, auth tests | P1 |
| C - Main assistant budget | `main` | assistant route, limiter/storage config, rate-limit tests | P1 |
| D - BFF CSRF | active feature | backend catch-all proxy, auth cookie/origin config, browser/API tests | P2 |
| E - LeetCode rendering | active feature | list/detail renderer, parser/sync trust boundary, rendering tests | P2 |
| F - CI authority | active feature | `.github/workflows/deploy.yml`, repo Actions settings, workflow validation | P2 |
| G - AWS login privacy | active feature and `aws-migration` | auth response, frontend confirmation flow, response tests | P2 |
| H - Main username privacy | `main` | username lookup and recovery/login flow | P2 |
| J - Main Supabase signup and redirect | `main` | frontend auth actions, callback origin, auth redirect utility, profile cache fallback | P2 |
| I - AWS deployment hardening | active feature | ALB, ElastiCache ACL, TLS and deployment settings | P2/P3 |
| K - Per-user local folder cache | active feature and `aws-migration` | questions page, QuestionDrawer localStorage lifecycle and account-switch tests | P3 |
| L - In-flight API account isolation | main and active feature | shared api.ts request map, signout lifecycle, account-switch tests | P2 |

## Audit boundaries

- The worktree at `c746a2127b10e506895df3143d15216f5586517d` was active; `main` at `2d93e08c80cf5bc7a929acc7109d41a2366a2ced`; `aws-migration` at `a61c6114782eb8d7d6c5ffa66593927a06763799`.
- Current untracked documents and agent guidance were included. The ignored `.env` was not read. No live credentials, AWS state, databases, or users were inspected.
- No source-code fixes were made. This document is a remediation plan, not proof of runtime exploitability or audit completion.
- Formal coverage/findings validators failed before input processing with `OS no-follow and nonblocking input protection is unavailable`. The audit run remains incomplete until a supported isolated runtime and final coverage review are available.






