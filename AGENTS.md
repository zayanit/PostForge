# Repository Guidelines

## Project Structure

- `frontend/` contains the Next.js 15 App Router application and Playwright tests.
- `backend/` contains the FastAPI service, SQLAlchemy stores/models, and pytest suites.
- `supabase/migrations/` contains ordered PostgreSQL schema, RLS, Vault, and Storage migrations.
- `specs/` contains feature specifications, plans, contracts, quickstarts, and task checklists.
- `docs/` and `scripts/` contain deployment/runbook documentation and container helpers.

## Build, Test, and Development Commands

Run `make help` for the complete command list. Common workflows are:

```bash
make install                         # Install frontend and backend dependencies
make supabase-start                  # Start the local Supabase/Docker stack
make dev                             # Run backend and frontend development servers
make test-backend                   # Run backend pytest suites from the repository root
cd frontend && npm run lint          # Run ESLint
cd frontend && npx tsc --noEmit     # Type-check TypeScript
cd frontend && npx playwright test  # Run browser tests
make build                          # Build the production container image
```

Real-Supabase integration tests require exported values from `backend/.env`, including `DATABASE_URL`, and a running local stack.

## Coding Style and Naming

Use four-space indentation for Python and two spaces for TypeScript/TSX. Follow existing FastAPI dependency, Pydantic model, and service-store patterns. Use `snake_case` for Python names and API fields, `PascalCase` for React components/types, and descriptive kebab-case feature directories such as `specs/004-provider-keys/`. Keep secrets, raw provider keys, Vault IDs, and SQL details out of responses and logs. Run ESLint and TypeScript checks before submitting frontend changes.

## Testing Guidelines

Name Python tests `test_*.py` and test functions `test_<behavior>`. Keep contract tests in `backend/tests/contract/`, unit tests in `backend/tests/unit/`, and real Supabase coverage in `backend/tests/integration/`. Add focused Playwright coverage under `frontend/tests/e2e/`. Run the narrowest relevant tests first, then the full backend suite and frontend checks.

## Commits and Pull Requests

Use concise imperative commit subjects, typically describing the completed feature or fix (for example, `Complete provider key activation`). Pull requests should explain the behavior changed, list verification commands and results, identify migrations or security implications, and include screenshots for meaningful UI changes. Keep spec/task status synchronized with verified work.

## Security and Configuration

Never commit `.env` files, service-role keys, provider credentials, or decrypted secrets. Apply Supabase migrations locally before integration testing, and preserve the repository’s RLS, Vault isolation, ownership, hard-delete, and opaque-error boundaries.
