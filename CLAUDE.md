# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PostForge is a multi-brand SaaS for generating social-media images (BYOK — users
supply their own OpenAI/Gemini API keys). The full product design lives in
`docs/implementation-plan.md` (schema, API surface, generation pipeline, frontend
structure, build order across 8 phases). **Only Phase 1 (auth/profile) and Phase 2
(Dockerization) are implemented so far** — brands, brand kits, provider keys, and
image generation itself (Phases 3–7) do not exist in code yet. Don't assume routes,
tables, or UI from the implementation plan exist until you've checked.

The authoritative product rules are in `.specify/memory/constitution.md`, not this
file — read it before making architectural decisions. Key non-negotiables from it:
brand-based tenancy (one brand, one owner, no sharing), hard delete (DB rows *and*
storage assets, never soft delete), provider keys never logged or sent to the
client, PNG-only output, official provider endpoints only (no proxies).

## Spec-driven workflow (GitHub spec-kit)

This repo is developed feature-by-feature through spec-kit, not ad hoc. Each feature
gets a numbered directory under `specs/NNN-feature-name/` (e.g. `specs/001-user-auth-profile/`,
`specs/002-dockerization/`) containing `spec.md`, `plan.md`, `research.md`,
`data-model.md`, `contracts/`, `quickstart.md`, and `tasks.md`, produced in that order
by the `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` →
`/speckit-analyze` → `/speckit-implement` command sequence. `.specify/feature.json`
tracks which feature directory is currently active. When picking up work on an
existing feature, read its `spec.md` and `tasks.md` first — task checkboxes
(`- [X]`/`- [ ]`) reflect real completion state, not the git log.

Constitution changes go through `/speckit-constitution`; any amendment must bump the
version and update the Sync Impact Report at the top of the file.

## Architecture

**Monorepo, three deployable pieces wired together at runtime, not build time:**

- `frontend/` — Next.js 14 (App Router, TypeScript). Route groups: `(auth)` for
  signup/login/forgot-password/reset-password, `(dashboard)` for the authenticated
  app (currently just `/` and `/account`). `middleware.ts` guards `/` and `/account*`
  server-side via Supabase session cookies — route groups don't add URL segments, so
  a page must live *inside* the group folder to inherit its layout (a past bug had
  the dashboard page as a sibling of `(dashboard)/`, silently skipping the layout).
- `backend/` — FastAPI (Python 3.11), routes under `/api/v1/...` except the
  unauthenticated `/health`. Structure: `app/routes/` (HTTP layer) → `app/services/`
  (business logic, e.g. `login_guard.py`, `profile_store.py`) → `app/models/`
  (Pydantic). `app/config.py` centralizes env var loading and holds the shared
  SQLAlchemy engine (`get_engine()`, cached, required for anything touching
  `login_attempts` or `profiles`).
- `supabase/` — Postgres schema via numbered migrations, RLS policies, Supabase Auth.
  `supabase/config.toml` is intentionally non-default in a few places (see comments
  inline): `minimum_password_length = 8` (Supabase's own default is 6), local mail
  service is `local_smtp`/Mailpit (not Inbucket — the CLI version in use here
  renamed it), `[analytics]` disabled (Logflare healthcheck was flaky locally).
- Single container (`Dockerfile`, `scripts/container-entrypoint.sh`,
  `scripts/container-healthcheck.sh`, `docs/docker.md`) — see "Container packaging"
  below.

**Auth**: Signup, logout, and password reset go straight from the frontend to
Supabase Auth via `@supabase/ssr`/`@supabase/supabase-js` — no backend involvement.
Login is the one exception: it's proxied through `POST /api/v1/auth/login` on the
backend specifically so failed-attempt lockout (5 attempts → 15 min lock, tracked in
the `login_attempts` table) can be enforced identically for registered and
unregistered emails, so the response can't be used to enumerate accounts.
`backend/app/auth.py`'s `get_current_user()` verifies JWTs by checking the token's
own `alg` header first — HS256 (legacy shared-secret projects) uses
`SUPABASE_JWT_SECRET` directly; anything else (e.g. ES256) fetches the signing key
from the project's `/auth/v1/.well-known/jwks.json` via `PyJWKClient`. Don't assume
one signing scheme — real Supabase projects can use either depending on when they
were created.

**RLS is necessary but not sufficient**: every table needs both `ENABLE ROW LEVEL
SECURITY`/`FORCE ROW LEVEL SECURITY` *and* base `GRANT`s to `authenticated`/
`service_role` — RLS policies narrow access that a `GRANT` must first allow. A table
with correct RLS but missing `GRANT`s fails with "permission denied" even for
`service_role` bypassing RLS entirely (see `supabase/migrations/00013_...`).

**Login lockout concurrency**: `login_guard.py`'s `record_failed_attempt()` is a
single `INSERT ... ON CONFLICT DO UPDATE` with `CASE` expressions, not a
SELECT-then-UPDATE — this avoids a lost-update race when concurrent failed logins hit
the same row. Only 400-class "invalid credentials" responses increment the counter;
502-class provider-unavailable responses must not, per `research.md` in the auth spec.

**Runtime config, not build-time config**: `frontend/lib/runtime-env.ts` reads
`NEXT_PUBLIC_*` values via `process.env` on the server and
`window.__POSTFORGE_PUBLIC_ENV__` on the client, rather than letting Next.js bake
them into the build. This exists because one container image must run against
different Supabase projects without rebuilding — don't reintroduce direct
`process.env.NEXT_PUBLIC_*` reads in client components.

**API access through one port**: `next.config.js` rewrites `/api/:path*` to
`NEXT_SERVER_API_URL` (defaults to `http://127.0.0.1:8000`) so the browser only ever
talks to the Next.js port; the backend is never bound to a public interface (see
Container packaging).

## Container packaging

A single multi-stage `Dockerfile` builds the Next.js frontend and installs backend
dependencies from a hash-locked `backend/requirements.lock` (generated via
`pip-compile --generate-hashes`; regenerate it if `requirements.txt` changes — the
build uses `pip install --require-hashes`, so it'll fail without the lock file
kept in sync), then combines both into one Debian-slim runtime image running as a
non-root user. Base images are pinned by digest (`@sha256:...`), not floating tags.

`scripts/container-entrypoint.sh` runs under `tini` as PID 1, starts `uvicorn`
(`127.0.0.1:8000`, never public) and `next start` (public port) as background jobs,
and independently restarts whichever one crashes (via `wait -n` + PID tracking) —
the other process and the container itself keep running. This is deliberate: no
backoff/retry-limit policy exists by design (see `contracts/entrypoint.md` in the
Dockerization spec) — a crash-looping process is meant to surface via repeated
healthcheck failures, not be silently smoothed over.

`scripts/container-healthcheck.sh` checks `127.0.0.1:8000/health` (backend, no auth,
no DB/external calls) and `127.0.0.1:3000/login` (frontend — note: *not* `/`, which
is behind the auth-guard middleware and would redirect; `/login` is the actual public
route). Both checks require an explicit `2xx` with redirects disabled
(`--max-redirs 0`) — `curl -f` alone isn't enough since it treats redirects as
success. Health reflects only these two local processes; it deliberately never
calls Supabase, so a Supabase outage doesn't flap container health.

Full behavioral contracts: `specs/002-dockerization/contracts/entrypoint.md` and
`.../healthcheck.md`. Operational runbook (build/run/deploy/troubleshoot):
`docs/docker.md`.

## Commands

**Frontend** (`frontend/`):
```bash
npm run dev     # local dev server
npm run build   # production build
npm run start   # run a production build
npm run lint    # next lint
npx tsc --noEmit                 # type-check without emitting
npx playwright test              # e2e tests (frontend/tests/e2e/) — needs the app + Supabase running
```

**Backend** (run from repo root, not `backend/` — imports are `backend.app.*`):
```bash
backend/.venv/bin/python -m pytest backend/tests -q            # all tests
backend/.venv/bin/python -m pytest backend/tests/contract/test_me.py -q   # single file
backend/.venv/bin/python -m pytest backend/tests -k test_name -q         # single test
```
Integration tests (`backend/tests/integration/`) that hit real Supabase endpoints
skip themselves via `pytest.skip` if `SUPABASE_URL`/`SUPABASE_SECRET_KEY` aren't set
— they need `supabase start` running first to actually execute, not just collect.

**Supabase** (local dev):
```bash
supabase start      # starts Postgres, Auth, Studio, local Mailpit, etc.
supabase stop
supabase migration up   # apply new migrations under supabase/migrations/
```

**Docker**:
```bash
docker build --platform linux/amd64 -t postforge:local .
docker run -d --name postforge --platform linux/amd64 --env-file .env.docker -p 3000:3000 postforge:local
```
See `docs/docker.md` for the full required env var list and `specs/002-dockerization/quickstart.md`
for end-to-end validation scenarios (including a deterministic crash-restart test using
`kill -STOP`/`kill -CONT` rather than an outright `kill`, which races the entrypoint's
own restart and makes the unhealthy transition non-deterministic to observe).

## Conventions worth knowing before editing

- Backend error responses are always `{"error": {"code", "message", "request_id"}}`
  (see `_error_response()` in `main.py`); match this shape for new endpoints.
- Structured JSON logging only — never log secrets, tokens, or full env values.
  This is enforced by convention (checked in review), not by a linter.
- Frontend fetches to the backend should go through defensive try/catch/finally so a
  network failure clears loading state and shows a generic error, rather than hanging.
- Avatar URL / full name validation must match exactly between the Pydantic model
  (`backend/app/models/profile.py`) and the Postgres `CHECK` constraint in the
  migration — a validator that's looser than the DB constraint lets requests pass
  Pydantic and then fail at the DB layer.
