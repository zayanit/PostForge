# Tasks: Accessible Sign-up Flow

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md)

## Phase 1: Setup

- [x] T001 Confirm existing auth routes and Supabase signup behavior in `frontend/app/(auth)/login/page.tsx` and `frontend/app/(auth)/signup/page.tsx`

## Phase 2: Foundational

- [x] T002 Confirm no backend, database, or environment changes are required in `backend/` and `supabase/`

## Phase 3: User Story 1 - Discover sign-up from login (P1)

**Independent test**: From `/login`, activate the signup link and reach `/signup`; from `/signup`, activate the sign-in link and return to `/login`.

- [x] T003 [US1] Add an accessible `Sign up` link targeting `/signup` in `frontend/app/(auth)/login/page.tsx`
- [x] T004 [US1] Add an accessible `Sign in` link targeting `/login` in `frontend/app/(auth)/signup/page.tsx`
- [x] T005 [P] [US1] Add navigation and client-side validation regression coverage in `frontend/tests/e2e/signup-flow.spec.ts`

## Phase 4: User Story 2 - Complete account creation (P1)

**Independent test**: Submit an invalid signup form and verify field errors; submit valid credentials against local Supabase and verify the existing success state.

- [x] T006 [US2] Preserve and verify the existing eight-character validation, pending state, and success/error feedback in `frontend/app/(auth)/signup/page.tsx`

## Phase 5: Polish and Validation

- [x] T007 Run frontend lint and the signup Playwright test from `frontend/`
- [x] T008 Run the frontend production build from `frontend/`
- [x] T009 Update this task file and the feature quickstart with final verification results

## Dependencies

User Story 1 and User Story 2 can be implemented independently after setup. Validation follows implementation.

## Implementation Strategy

Deliver the MVP by wiring the reciprocal links and regression test first. Then verify the existing signup behavior and run lint/build checks.
