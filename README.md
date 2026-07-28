# PostForge

PostForge is a multi-brand SaaS for managing brand identities and securely connecting OpenAI and Google Gemini API keys (BYOK). The current product includes authentication, profiles, Brand CRUD, provider-key storage/validation/activation/deletion, retryable Vault and Storage cleanup, and a Docker deployment image.

Brand Kit interviews and image generation are planned but are not implemented yet. Live disposable OpenAI/Gemini validation remains a release-verification step; deterministic provider tests and all local automated checks are in place.

## Technology

- Frontend: Next.js 15, React, TypeScript, Tailwind CSS
- Backend: FastAPI, Python, SQLAlchemy
- Platform: Supabase Auth, PostgreSQL, Vault, Storage, and local Docker
- Deployment: one combined container for Bunny Magic Containers

## Run Locally

### Prerequisites

Install Node.js 20.x, Python 3.11+, Docker Desktop, and the [Supabase CLI](https://supabase.com/docs/guides/cli). Run all commands below from the repository root.

### 1. Install dependencies

```bash
make install
```

### 2. Start Supabase

```bash
make supabase-start
supabase status
```

Keep the status output available. You need its `API_URL`, `SECRET_KEY`, `JWT_SECRET`, `DB_URL`, and `PUBLISHABLE_KEY` values.

### 3. Configure the backend

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and set:

```dotenv
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_SECRET_KEY=<SECRET_KEY from supabase status>
SUPABASE_JWT_SECRET=<JWT_SECRET from supabase status>
DATABASE_URL=<DB_URL from supabase status>
```

`DATABASE_URL` is backend-only. Never put it in a `NEXT_PUBLIC_*` variable or commit `backend/.env`.

### 4. Configure the frontend

```bash
cp frontend/.env.local.example frontend/.env.local
```

Set `NEXT_PUBLIC_SUPABASE_URL` to the local `API_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` to `PUBLISHABLE_KEY`. Leave `NEXT_PUBLIC_API_URL=/api` and `NEXT_SERVER_API_URL=http://127.0.0.1:8000` unchanged.

### 5. Start the application

Use one terminal for the backend and another for the frontend:

```bash
# Terminal 1
make dev-backend

# Terminal 2
make dev-frontend
```

Open [http://localhost:3000](http://localhost:3000), create an account, confirm it through the local Mailpit inbox if required, and create a brand. Provider keys are available from the brand’s **Manage provider keys** page.

To stop Supabase later:

```bash
make supabase-stop
```

## Test and Build

```bash
make test-backend                    # Full backend suite; requires Supabase for integration tests
cd frontend && npm run lint          # ESLint
cd frontend && npx tsc --noEmit     # TypeScript check
cd frontend && npm run build         # Production frontend build
cd frontend && npx playwright test  # Browser tests
docker build --platform linux/amd64 -t postforge:local .
```

## Project Layout

```text
frontend/   Next.js application and Playwright tests
backend/    FastAPI application and pytest suites
supabase/   PostgreSQL migrations, Auth, RLS, Vault, and Storage configuration
specs/      Feature specifications, plans, contracts, and task checklists
docs/       Docker and deployment runbooks
scripts/    Container entrypoint and healthcheck helpers
```

Read [docs/docker.md](docs/docker.md) for container deployment and [AGENTS.md](AGENTS.md) for contributor guidance. Product constraints are documented in [.specify/memory/constitution.md](.specify/memory/constitution.md).
