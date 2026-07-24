# PostForge

PostForge is a multi-brand SaaS for generating social-media images. Users create
brands, complete a short brand-kit interview, connect their own OpenAI/Gemini API
keys (BYOK — no billing in MVP), and generate PNG images sized for each platform.

The full product design — database schema, API surface, generation pipeline,
frontend structure, and build order — lives in [`docs/implementation-plan.md`](docs/implementation-plan.md).
The non-negotiable product rules (brand-based tenancy, hard delete, key secrecy,
official-endpoints-only, PNG-only output) live in
[`.specify/memory/constitution.md`](.specify/memory/constitution.md).

**Current status**: only account authentication/profile management and the Docker
packaging are implemented so far. Brands, brand kits, provider keys, and image
generation itself are designed but not yet built.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router, TypeScript) |
| Backend | FastAPI (Python 3.11) |
| Auth, database, storage | Supabase |
| Hosting | Bunny Magic Containers (single container image) |
| Image providers | OpenAI, Google Gemini |

## Prerequisites

- Node.js 20.x
- Python 3.11+
- [Supabase CLI](https://supabase.com/docs/guides/cli) and Docker (Supabase's local
  stack runs in containers)
- Docker, if you want to build/run the packaged container image

## Local development setup

### 1. Start Supabase

```bash
supabase start
```

This starts a local Postgres instance, Supabase Auth, Studio, and a local mail
inbox (Mailpit) for testing signup/password-reset emails. `supabase start` prints
the local API URL and keys you'll need below.

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# then fill in SUPABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_JWT_SECRET, DATABASE_URL
# with the values `supabase start` printed

uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install

cp .env.local.example .env.local
# then fill in NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY

npm run dev
```

Visit `http://localhost:3000`.

## Testing

```bash
# Backend — run from the repository root, not backend/ (imports are backend.app.*)
backend/.venv/bin/python -m pytest backend/tests -q

# Frontend type-check
cd frontend && npx tsc --noEmit

# Frontend end-to-end (requires the dev server and Supabase running)
cd frontend && npx playwright test
```

Backend integration tests that hit real Supabase endpoints skip themselves
automatically if `SUPABASE_URL`/`SUPABASE_SECRET_KEY` aren't set.

## Running as a single container

The app also builds into one deployable container image (frontend + backend, one
public port):

```bash
docker build --platform linux/amd64 -t postforge:local .
docker run -d --name postforge --platform linux/amd64 --env-file .env.docker -p 3000:3000 postforge:local
```

See [`docs/docker.md`](docs/docker.md) for the full required environment variables,
healthcheck/restart behavior, and how to deploy to Bunny Magic Containers.

## Project structure

```
frontend/     Next.js app (App Router)
backend/      FastAPI app
supabase/     Postgres migrations, Auth/RLS config
specs/        Spec-kit feature specs, plans, and tasks (see below)
docs/         Implementation plan and Docker runbook
Dockerfile, scripts/   Single-container packaging
```

## How this project is developed

Features are specified, planned, and task-broken-down before implementation using
[GitHub spec-kit](https://github.com/github/spec-kit). Each feature has its own
directory under `specs/NNN-feature-name/` with a spec, implementation plan,
research notes, and a task list. See [`CLAUDE.md`](CLAUDE.md) for more detail on
this workflow and the codebase's architecture.
