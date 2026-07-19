# Quickstart: User Authentication & Profile

Validates that signup, login (including lockout), session enforcement, profile edit,
and password reset all work end-to-end. See `data-model.md` for schema and
`contracts/` for the exact request/response shapes exercised below.

## Prerequisites

- Local Supabase stack running (`supabase start`), with migrations applied:
  - `profiles` (from `docs/implementation-plan.md`)
  - `login_attempts` (this feature — see `data-model.md`)
- Backend running locally: `uvicorn app.main:app --reload` (port 8000)
- Frontend running locally: `npm run dev` (port 3000), pointed at the local backend/Supabase

## Scenario 1 — Signup → dashboard (Story 1, SC-001)

1. Navigate to `/signup`.
2. Submit a new email and an 8+ character password.
3. **Expect**: redirected to the dashboard; a row exists in `profiles` for the new
   `auth.users.id` with `full_name` and `avatar_url` both `NULL`.
4. Repeat signup with the same email.
5. **Expect**: rejected with a clear "already registered" error (FR-002); no duplicate
   account or profile row created.

## Scenario 2 — Login, logout, session enforcement (Story 2, SC-002, SC-006)

1. Navigate to `/login`, sign in with the account from Scenario 1.
2. **Expect**: signed in, redirected to dashboard within 15 seconds of correct submission.
3. Log out.
4. **Expect**: session ends; navigating directly to `/account` redirects to `/login`.
5. Attempt `GET /api/v1/me` with no `Authorization` header.
6. **Expect**: `401 UNAUTHORIZED` (contracts/me.md).

## Scenario 3 — Failed login lockout (FR-006, FR-006a)

1. Attempt login with the correct email and a wrong password, 5 times in a row.
2. **Expect**: each of the first 4 attempts returns the generic `400 INVALID_CREDENTIALS`
   error (contracts/auth-login.md); the 5th failure triggers a lockout.
3. Attempt login again (even with the correct password) immediately after.
4. **Expect**: `429 ACCOUNT_TEMPORARILY_LOCKED`, and no Supabase Auth call is made (no
   change in Supabase's own failure metrics for this attempt).
5. Repeat steps 1–4 using an email that was never registered.
6. **Expect**: identical response codes/bodies to steps 2 and 4 — no observable
   difference from the registered-email case (verifies FR-006's non-enumeration
   guarantee holds even under lockout).
7. Wait for the lockout window to pass, then log in with the correct password.
8. **Expect**: success, and `login_attempts` for that email is cleared.

## Scenario 4 — View and edit profile (Story 3, SC-003, SC-004)

1. Signed in, navigate to `/account`.
2. **Expect**: current email, full name (empty), and avatar (empty) are displayed.
3. Submit a valid full name and avatar URL.
4. **Expect**: saved immediately; reload confirms persistence.
5. Submit an empty/whitespace-only name.
6. **Expect**: rejected with an explanatory error (FR-010); previous values still shown.
7. As a second user (different account), attempt `PATCH /api/v1/me` is not possible to
   target the first user's profile — there is no user-identifying request parameter, so
   this is confirmed structurally (contracts/me.md) rather than by a bypassable check.
   Additionally confirm directly against Postgres: querying `profiles` as the second
   user's `auth.uid()` returns only their own row (RLS check, data-model.md).

## Scenario 5 — Password reset (Story 4, SC-005)

1. From `/login`, request a password reset for the Scenario 1 account's email.
2. **Expect**: a reset email is sent (or, in local dev, visible in the Supabase Inbucket/
   mail trap).
3. Repeat the request for an email that was never registered.
4. **Expect**: identical UI response to step 2 (FR-012 — no existence leak).
5. Follow the emailed link, set a new password (8+ characters).
6. **Expect**: login succeeds with the new password and fails with the old one.

## Definition of Done check (constitution VII, feature-scoped subset)

- [ ] RLS verified: a second user's Postgres session cannot read or write another user's
      `profiles` row (Scenario 4, step 7).
- [ ] `login_attempts` confirmed to have RLS enabled with no client-facing policies
      (only the backend's service-role connection can read/write it).
