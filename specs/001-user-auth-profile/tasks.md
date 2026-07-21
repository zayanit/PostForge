---

description: "Task list template for feature implementation"
---

# Tasks: User Authentication & Profile

**Input**: Design documents from `/specs/001-user-auth-profile/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present)

**Tests**: Included — plan.md's Technical Context commits to a testing stack (pytest + httpx backend, Playwright frontend) and research.md § 5 makes this an explicit decision, so test tasks are generated per contract/story.

**Organization**: Tasks are grouped by user story (from spec.md, in priority order) to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Exact file paths are included in every description

## Path Conventions

Web app per plan.md Project Structure: `backend/app/`, `backend/tests/` and `frontend/app/`, `frontend/lib/`, `frontend/tests/` at repository root; database migrations under `supabase/migrations/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization — this is a greenfield repo with no `backend/`/`frontend/` code yet.

- [ ] T001 Create `backend/` and `frontend/` directory scaffolding per plan.md Project Structure
- [ ] T002 Initialize FastAPI backend project in `backend/` (`requirements.txt` with fastapi, uvicorn, pydantic, sqlalchemy, alembic, httpx; `backend/app/main.py` skeleton; `backend/.env.example`)
- [ ] T003 [P] Initialize Next.js 14 frontend project in `frontend/` (TypeScript, App Router, Tailwind CSS, shadcn/ui, `@supabase/supabase-js`; `frontend/package.json`)
- [ ] T004 [P] Configure backend linting/formatting (ruff + black) in `backend/pyproject.toml`
- [ ] T005 [P] Configure frontend linting/formatting (ESLint + Prettier) in `frontend/.eslintrc.json`
- [ ] T006 [P] Initialize local Supabase project config in `supabase/config.toml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T007 [P] Create `profiles` table migration in `supabase/migrations/00002_create_profiles.sql` per data-model.md (columns, CHECK constraints, RLS enabled with owner policy)
- [ ] T008 [P] Create `login_attempts` table migration in `supabase/migrations/00010_create_login_attempts.sql` per data-model.md (RLS enabled, zero client-facing policies) — numbered `00010`+ to avoid colliding with `00003_create_brands.sql`/`00004_create_brand_kits.sql`, already reserved for the Brand feature in docs/implementation-plan.md
- [ ] T009 [P] Implement Supabase JWT verification dependency in `backend/app/auth.py` (validates `Authorization: Bearer` token, exposes current user id to routes)
- [ ] T010 [P] Implement error response envelope and exception handlers in `backend/app/main.py` matching the `{"error": {"code","message","request_id"}}` shape from contracts/
- [ ] T011 [P] Implement backend settings loader in `backend/app/config.py` (`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, etc. from env)
- [ ] T012 [P] Implement Supabase browser client in `frontend/lib/supabase/client.ts`
- [ ] T013 [P] Implement Supabase server client in `frontend/lib/supabase/server.ts`
- [ ] T014 Implement auth-guard middleware in `frontend/middleware.ts` redirecting unauthenticated requests to `/login` (FR-008; depends on T013)

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - Create an account (Priority: P1) 🎯 MVP

**Goal**: A visitor can sign up with email/password and a profile is created for them automatically.

**Independent Test**: Submit the signup form with a valid, unused email and an 8+ character password; verify a `profiles` row exists for the new account. Repeat with the same email and verify it's rejected with no duplicate created.

### Tests for User Story 1

- [ ] T015 [P] [US1] Integration test verifying a `profiles` row is auto-created after signup, in `backend/tests/integration/test_signup_profile_creation.py` — MUST also assert FR-003's boundary directly against Supabase Auth (not just client-side validation): a 7-character password is rejected by `supabase.auth.signUp()` and an 8-character password is accepted, proving `minimum_password_length = 8` in supabase/config.toml is actually enforced

### Implementation for User Story 1

- [ ] T016 [US1] Create Postgres trigger function + trigger `on_auth_user_created` that inserts a blank `profiles` row on signup, in `supabase/migrations/00011_create_profile_signup_trigger.sql` (depends on T007; numbered `00011` for the same reason as T008)
- [ ] T017 [US1] Implement signup page in `frontend/app/(auth)/signup/page.tsx` calling `supabase.auth.signUp()` (depends on T012)
- [ ] T018 [US1] Add signup form validation (email format, 8+ character password per FR-003) and duplicate-email error display in `frontend/app/(auth)/signup/page.tsx` (depends on T017)

**Checkpoint**: User Story 1 is fully functional and testable independently — signup creates an account and profile; duplicate signup is rejected.

---

## Phase 4: User Story 2 - Log in and log out (Priority: P1)

**Goal**: A returning user can log in (with brute-force lockout protection) and log out; unauthenticated users are denied access to authenticated pages.

**Independent Test**: Log in with correct credentials and reach the dashboard; log in with a wrong password and get a generic error; fail 5 times in a row and get locked out; log out and confirm protected pages redirect to `/login`.

### Tests for User Story 2

- [ ] T019 [P] [US2] Contract test for `POST /api/v1/auth/login` (200 success, 400 invalid credentials, 429 locked out, 502 provider unavailable) per contracts/auth-login.md, in `backend/tests/contract/test_auth_login.py`
- [ ] T020 [P] [US2] Integration test for the 5-consecutive-failure lockout flow (including identical behavior for an unregistered email) AND a transient-failure case proving a simulated Supabase timeout/5xx returns 502 without incrementing `login_attempts.failed_count`, in `backend/tests/integration/test_login_lockout.py`

### Implementation for User Story 2

- [ ] T021 [P] [US2] Create `LoginAttempt` model in `backend/app/models/login_attempt.py`
- [ ] T022 [US2] Implement `login_guard` service (check/increment/reset lockout state) in `backend/app/services/login_guard.py` (depends on T021)
- [ ] T023 [US2] Implement `POST /api/v1/auth/login` route in `backend/app/routes/auth.py` — proxies Supabase Auth's password grant via `httpx`, applies `login_guard`, never logs password/tokens (depends on T022, T009)
- [ ] T024 [US2] Wire the auth router into `backend/app/main.py` (depends on T023)
- [ ] T025 [US2] Implement login page in `frontend/app/(auth)/login/page.tsx` calling backend `POST /api/v1/auth/login` (not direct Supabase call, per research.md §1; depends on T023)
- [ ] T026 [US2] Implement dashboard layout with a logout control in `frontend/app/(dashboard)/layout.tsx` calling `supabase.auth.signOut()` and redirecting to `/login` (depends on T012)
- [ ] T027 [P] [US2] End-to-end test for session enforcement (unauthenticated access to a protected route redirects to `/login`) in `frontend/tests/e2e/session-enforcement.spec.ts`

**Checkpoint**: User Stories 1 AND 2 both work independently — signup, login with lockout, logout, and session enforcement are all functional.

---

## Phase 5: User Story 3 - View and edit profile (Priority: P2)

**Goal**: A signed-in user can view and update their own full name and avatar, and never another user's.

**Independent Test**: Sign in, load the account page, edit name/avatar, save, reload and confirm persistence; submit invalid data and confirm rejection with prior values intact; confirm RLS blocks cross-user access at the database layer.

### Tests for User Story 3

- [ ] T028 [P] [US3] Contract test for `GET /api/v1/me` and `PATCH /api/v1/me` per contracts/me.md, in `backend/tests/contract/test_me.py` — MUST include a reject-then-reread case: submit an invalid `PATCH` (e.g., empty name), assert `400 VALIDATION_ERROR`, then `GET /api/v1/me` again and assert prior values are unchanged (SC-003's "0% partially-saved state" guarantee)
- [ ] T029 [P] [US3] Integration test verifying RLS blocks one user from reading/writing another user's `profiles` row, in `backend/tests/integration/test_profile_rls.py`

### Implementation for User Story 3

- [ ] T030 [P] [US3] Create `Profile` Pydantic schema in `backend/app/models/profile.py` (validation matching the `profiles` table CHECK constraints)
- [ ] T031 [US3] Implement `GET /api/v1/me` route in `backend/app/routes/me.py` (depends on T030, T009)
- [ ] T032 [US3] Implement `PATCH /api/v1/me` route with validation and rejection-leaves-prior-values behavior in `backend/app/routes/me.py` (depends on T030, T009)
- [ ] T033 [US3] Wire the `me` router into `backend/app/main.py` (depends on T031, T032)
- [ ] T034 [US3] Implement account settings page (view + edit form) in `frontend/app/(dashboard)/account/page.tsx` (depends on T026)
- [ ] T035 [US3] Add profile edit form validation (React Hook Form + Zod) matching backend constraints in `frontend/app/(dashboard)/account/page.tsx` (depends on T034)

**Checkpoint**: User Stories 1, 2, AND 3 all work independently.

---

## Phase 6: User Story 4 - Reset a forgotten password (Priority: P3)

**Goal**: A user who forgot their password can request a reset link by email and set a new password.

**Independent Test**: Request a reset for a known email and confirm identical behavior for an unregistered email; follow the reset link, set a new password, and confirm login works with the new password and not the old one.

### Tests for User Story 4

- [ ] T036 [P] [US4] End-to-end test for the password reset request + confirm flow in `frontend/tests/e2e/password-reset.spec.ts`

### Implementation for User Story 4

- [ ] T037 [US4] Implement forgot-password request page in `frontend/app/(auth)/forgot-password/page.tsx` calling `supabase.auth.resetPasswordForEmail()` (depends on T012)
- [ ] T038 [US4] Implement reset-password confirm page in `frontend/app/(auth)/reset-password/page.tsx` calling `supabase.auth.updateUser()` with the new password (depends on T012)
- [ ] T039 [US4] Add a "forgot password" link from the login page to the forgot-password page in `frontend/app/(auth)/login/page.tsx` (depends on T025, T037)

**Checkpoint**: All four user stories are independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T040 [P] Add structured logging (excluding any secret/token values) to `backend/app/routes/auth.py` and `backend/app/routes/me.py`
- [ ] T041 [P] Update `docs/implementation-plan.md` § API Endpoints to add the new `POST /api/v1/auth/login` endpoint, keeping the plan and implementation in sync
- [ ] T042 Security hardening pass: confirm `login_attempts` has RLS enabled with zero client-facing policies, and confirm no password or access/refresh token appears in any log output
- [ ] T043 Run all 5 `quickstart.md` validation scenarios end-to-end and record results
- [ ] T044 [P] Schedule the `login_attempts` retention cleanup as a daily `pg_cron` job per data-model.md's Retention/cleanup policy, in `supabase/migrations/00012_schedule_login_attempts_cleanup.sql`
- [ ] T045 Set the hosted (production) Supabase project's Auth "Minimum password length" to 8 via the Supabase dashboard/Management API (FR-003) — `supabase/config.toml`'s `minimum_password_length` only applies to local/self-hosted CLI instances, not an already-provisioned hosted project, so this MUST be applied manually and recorded as done before launch

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Stories (Phase 3–6)**: All depend on Foundational phase completion; proceed in priority order (US1 → US2 → US3 → US4) or in parallel if staffed, per the notes below
- **Polish (Phase 7)**: Depends on all four user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational — no dependency on other stories
- **User Story 2 (P1)**: Can start after Foundational — independently testable, though its login page (T025) is most naturally exercised once T017 (signup) has produced an account
- **User Story 3 (P2)**: Can start after Foundational — its frontend page (T034) depends on the dashboard layout introduced in US2 (T026); its backend routes (T031–T033) have no dependency on US1/US2 code
- **User Story 4 (P3)**: Can start after Foundational — its "forgot password" link (T039) depends on US2's login page (T025) existing to link from

### Within Each User Story

- Tests are written before their corresponding implementation task
- Models before services/routes
- Services before routes that use them
- Routes wired into `main.py` before frontend pages that call them
- Story complete before moving to the next priority (if working sequentially)

### Parallel Opportunities

- Setup: T003, T004, T005, T006 can run in parallel once T001/T002 land
- Foundational: T007–T013 can all run in parallel; only T014 has a same-phase dependency (on T013)
- Once Foundational completes, US1, US2, US3 (backend routes), and US4 can largely proceed in parallel across a team, with the noted cross-story frontend dependencies (US3's account page needs US2's dashboard layout; US4's login link needs US2's login page)
- All tasks marked [P] within a phase touch different files and can be parallelized

---

## Parallel Example: Foundational Phase

```bash
Task: "Create profiles table migration in supabase/migrations/00002_create_profiles.sql"
Task: "Create login_attempts table migration in supabase/migrations/00010_create_login_attempts.sql"
Task: "Implement Supabase JWT verification dependency in backend/app/auth.py"
Task: "Implement error response envelope in backend/app/main.py"
Task: "Implement backend settings loader in backend/app/config.py"
Task: "Implement Supabase browser client in frontend/lib/supabase/client.ts"
Task: "Implement Supabase server client in frontend/lib/supabase/server.ts"
```

## Parallel Example: User Story 2

```bash
Task: "Contract test for POST /api/v1/auth/login in backend/tests/contract/test_auth_login.py"
Task: "Integration test for lockout flow in backend/tests/integration/test_login_lockout.py"
Task: "Create LoginAttempt model in backend/app/models/login_attempt.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: signup + auto-profile-creation works independently
5. Demo if ready

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add US1 (signup) → validate independently → demo (MVP!)
3. Add US2 (login/logout/lockout) → validate independently → demo
4. Add US3 (profile view/edit) → validate independently → demo
5. Add US4 (password reset) → validate independently → demo
6. Run `quickstart.md` in full (T043) as the final cross-story validation

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: US1 (signup)
   - Developer B: US2 (login/lockout/logout) — backend routes first, independent of US1
   - Developer C: US3 backend routes (`GET`/`PATCH /api/v1/me`) — independent of US1/US2 backend work
3. US3's frontend page and US4 wait on US2's dashboard layout/login page landing first

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Login is backend-mediated (`POST /api/v1/auth/login`) specifically to satisfy FR-006a's lockout requirement — signup, logout, and password reset remain direct Supabase client calls (research.md §§1, 3)
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently
