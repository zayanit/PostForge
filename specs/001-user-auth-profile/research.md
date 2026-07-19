# Phase 0 Research: User Authentication & Profile

## 1. How to enforce FR-006a's 5-attempt lockout given Supabase Auth handles credentials

**Decision**: Add a thin backend endpoint, `POST /api/v1/auth/login`, that the frontend
calls instead of invoking `supabase.auth.signInWithPassword()` directly. The endpoint
checks/updates a `login_attempts` table (keyed by normalized email) before and after
calling Supabase Auth's password-grant token endpoint server-side via `httpx`.

**Rationale**: Supabase Auth's built-in abuse protection is project-wide/IP-based, not a
per-account "5 consecutive failed attempts" counter, so it cannot satisfy FR-006a as
specified without a proxy. Tracking attempts by normalized email (rather than by
`auth.users.id`) lets the same lockout logic apply uniformly whether or not the email is
registered, which is required to keep FR-006's non-enumeration guarantee intact — a
lockout that only ever triggers for real accounts would itself leak account existence
through timing/behavior differences.

**Alternatives considered**:
- *Rely solely on Supabase's project-level rate limiting*: Rejected — doesn't match the
  spec's explicit "5 consecutive failed attempts for that account" behavior, and the
  clarification session specifically chose per-account lockout over relying on platform
  defaults (Question 3, Option B over Option A).
- *Client-side attempt counting (localStorage)*: Rejected — trivially bypassed by clearing
  browser storage or switching devices; provides no real protection.
- *CAPTCHA after N failures instead of lockout*: Considered during clarification (Option
  C) but not selected; lockout was the chosen answer.

## 2. Session / token expiry duration

**Decision**: Use Supabase Auth's default JWT access token expiry (1 hour) with automatic
refresh-token rotation handled by the `@supabase/supabase-js` client. No custom session
management is built.

**Rationale**: The spec's Assumptions section already states authentication primitives
(including session/JWT issuance) are provided by Supabase Auth rather than built from
scratch. This was intentionally left as a deferred, low-impact item during clarification
since it's a platform configuration default, not a product decision — the spec's edge
case only requires that sessions expire on standard token expiry rather than lasting
indefinitely, which the default already satisfies.

**Alternatives considered**:
- *Custom shorter/longer expiry*: Rejected for MVP — no stated requirement justifies
  deviating from the platform default, and doing so would need additional Supabase Auth
  configuration work outside this feature's scope.

## 3. Signup and password reset flow: client-side vs. backend-mediated

**Decision**: Signup (`supabase.auth.signUp()`) and password reset request/confirm
(`supabase.auth.resetPasswordForEmail()` / `updateUser()`) are called directly from the
frontend via the Supabase client SDK. Only login is proxied through the backend.

**Rationale**: Neither signup nor password reset has a functional requirement that needs
backend mediation — Supabase's own duplicate-email handling satisfies FR-002, and FR-012's
identical-response requirement is already how `resetPasswordForEmail()` behaves natively
(it does not reveal whether the email exists). Introducing a backend proxy for these flows
would add complexity with no corresponding requirement driving it, which the Assumptions
section (auth primitives provided by Supabase, not rebuilt) argues against.

**Alternatives considered**:
- *Proxy all auth operations through the backend for consistency*: Rejected — only login
  has a requirement (FR-006a) that Supabase's client SDK cannot satisfy alone; applying
  the same proxy pattern elsewhere would be unjustified extra surface area.

## 4. Profile field validation rules

**Decision**: Reuse the `profiles` table's existing CHECK constraints from
`docs/implementation-plan.md` (`full_name` 2–120 chars when present, `avatar_url` must
match `^https?://.+` when present) as the backend (Pydantic) and frontend validation
rules for FR-010.

**Rationale**: These constraints already exist in the approved schema; duplicating them
in FR-010's implementation keeps the API layer, database, and spec consistent without
inventing new bounds.

**Alternatives considered**: None — this is a direct reuse of an existing, already-agreed
decision, not a new design question.

## 5. Testing approach

**Decision**: Backend contract/integration tests use `pytest` + `httpx.AsyncClient`
against a local Supabase instance (via `supabase start`); frontend end-to-end tests use
Playwright to drive the signup → login → profile-edit → logout flow and the lockout edge
case in a real browser.

**Rationale**: Matches the stack already fixed by the constitution (FastAPI backend,
Next.js frontend) and is the standard pairing for each; no project-specific testing
framework was specified elsewhere, and these are the most common choices for this stack
combination, keeping the decision low-risk and unsurprising to contributors.

**Alternatives considered**:
- *Frontend unit tests only (no E2E)*: Rejected — session/redirect/lockout behavior spans
  frontend and backend and is best verified end-to-end rather than mocked.
