# Implementation Plan: User Authentication & Profile

**Branch**: `001-user-auth-profile` | **Date**: 2026-07-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-user-auth-profile/spec.md`

## Summary

Deliver account creation, login/logout, session enforcement, profile view/edit, and
password reset, backed by Supabase Auth. Signup and password reset use the Supabase
Auth client SDK directly from the frontend (no custom backend logic needed). Login is
mediated by a new backend endpoint so the system can enforce the spec's 5-attempt
temporary lockout (FR-006a) uniformly — including for unregistered emails, to avoid
timing/behavior differences that would leak account existence (FR-006). Profile data
lives in a `profiles` table (1:1 with `auth.users`), exposed via `GET/PATCH /api/v1/me`
as already defined in `docs/implementation-plan.md`.

## Technical Context

**Language/Version**: TypeScript 5.x (Next.js 14, App Router) for frontend; Python 3.11+ for backend (FastAPI)

**Primary Dependencies**: `@supabase/supabase-js` (frontend, direct Supabase Auth calls for signup/logout/password-reset); FastAPI, Pydantic v2, SQLAlchemy + Alembic, `httpx` (backend, calls Supabase Auth's password-grant endpoint server-side for the login proxy)

**Storage**: Supabase PostgreSQL — `profiles` and `login_attempts` tables (this feature); `auth.users` (Supabase-managed, not modified directly)

**Testing**: pytest + httpx (backend contract/integration tests against a local Supabase instance); Playwright (frontend end-to-end: signup, login, lockout, profile edit, password reset)

**Target Platform**: Web — single Bunny Magic container per `docs/implementation-plan.md` (Next.js serves the one public port; FastAPI listens internally only)

**Project Type**: Web application (frontend + backend, monorepo root-level `frontend/` and `backend/`, per `docs/implementation-plan.md` Files to Create)

**Performance Goals**: SC-001 (signup → dashboard under 2 minutes), SC-002 (login → dashboard under 15 seconds) — both dominated by human interaction and network latency, not raw backend throughput; no separate throughput target for MVP

**Constraints**: FastAPI is never exposed to the public internet directly (single public port is Next.js); the login proxy endpoint must not reveal whether an email is registered (FR-006) even while enforcing lockout (FR-006a); profile field validation must match the `profiles` table's existing CHECK constraints in `docs/implementation-plan.md`

**Scale/Scope**: MVP — small early user base; this feature covers only authentication and the user's own profile, nothing brand-related

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applicability to this feature | Status |
|---|---|---|
| I. Product Truth (brand-based tenancy, BYOK, image generation) | Not applicable — this feature has no brand, key, or generation concepts; it establishes the account a brand will later belong to | Pass (N/A) |
| II. Non-Negotiables (brand isolation, hard delete, key secrecy, official endpoints, PNG-only) | Not applicable — no brands, generations, or provider keys exist in this feature | Pass (N/A) |
| III. Tech Constraints (Next.js 14, FastAPI, Supabase, Bunny Magic) | Applicable — feature is built entirely on the fixed stack, no deviation | Pass |
| IV. Data Rules (generation/brand-kit/provider-key storage rules) | Not applicable — no such records in this feature | Pass (N/A) |
| V. UX Rules (prompt-first, brand-kit interview, presets, history) | Not applicable — no generation UX in this feature | Pass (N/A) |
| VI. Security Rules (RLS on all tables; server-side verification; no secrets/PII in logs) | Applicable — `profiles` and `login_attempts` MUST have RLS enabled; login proxy MUST NOT log passwords or tokens | Pass, enforced in design (see data-model.md) |
| VII. Definition of Done (brand-kit/provider/hard-delete checks) | Partially applicable — RLS-tested item applies (to `profiles`); brand-kit, provider, and hard-delete items are N/A for this feature | Pass (feature-scoped subset: RLS tested) |

No violations requiring justification — every non-applicable principle is non-applicable
because this feature precedes brand/generation concepts entirely, not because a rule was
bypassed. This reading is now ratified explicitly in the constitution itself (Principle I,
v1.1.0): foundational account infrastructure is exempted from the "sole product
capability" rule rather than relying on an unratified interpretation in this plan. No
Complexity Tracking entries needed.

**Post-Phase 1 re-check**: Design added one new table (`login_attempts`) and one new
endpoint (`POST /api/v1/auth/login`, see `contracts/auth-login.md`). Both keep the
feature compliant: `login_attempts` has RLS enabled with zero client-facing policies
(service-role only, see `data-model.md`), and the login contract explicitly forbids
logging passwords or tokens. No new violations introduced.

## Project Structure

### Documentation (this feature)

```text
specs/001-user-auth-profile/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output
│   ├── auth-login.md
│   └── me.md
└── tasks.md              # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── main.py                     # FastAPI app, CORS, routers
│   ├── config.py                   # Settings from env
│   ├── auth.py                     # JWT verification middleware (existing dependency for all authenticated routes)
│   ├── models/
│   │   ├── profile.py
│   │   └── login_attempt.py        # New: lockout tracking model
│   ├── routes/
│   │   ├── me.py                   # GET/PATCH /api/v1/me
│   │   └── auth.py                 # New: POST /api/v1/auth/login (lockout-aware proxy)
│   └── services/
│       └── login_guard.py          # New: failed-attempt counting + lockout logic
└── tests/
    ├── contract/
    │   ├── test_me.py
    │   └── test_auth_login.py
    └── integration/
        ├── test_signup_profile_creation.py
        ├── test_login_lockout.py
        └── test_profile_rls.py

frontend/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   ├── signup/page.tsx
│   │   ├── forgot-password/page.tsx  # Password reset request
│   │   └── reset-password/page.tsx   # Password reset confirm
│   └── (dashboard)/
│       ├── layout.tsx                # Nav + logout control
│       └── account/page.tsx          # Profile view/edit
├── lib/
│   └── supabase/
│       ├── client.ts                # Browser client (signup, logout, password reset)
│       └── server.ts                # Server client
├── tests/
│   └── e2e/
│       ├── session-enforcement.spec.ts
│       └── password-reset.spec.ts
└── middleware.ts                    # Redirects unauthenticated requests to /login

supabase/
└── migrations/
    ├── 00002_create_profiles.sql              # Already defined in docs/implementation-plan.md
    ├── 00010_create_login_attempts.sql        # New, this feature — numbered to avoid colliding
    └── 00011_create_profile_signup_trigger.sql  # with 00003/00004, reserved for Brand/Brand Kit
```

**Structure Decision**: Root-level `backend/` and `frontend/` directories (not nested under
`apps/`), matching the concrete layout already specified in `docs/implementation-plan.md`
§ Files to Create. This feature adds one new backend route module (`routes/auth.py`), one
new service (`services/login_guard.py`), one new model/migration (`login_attempts`), and
the auth/account pages on the frontend. No new top-level directories are introduced.

## Complexity Tracking

*No entries — no Constitution Check violations.*
