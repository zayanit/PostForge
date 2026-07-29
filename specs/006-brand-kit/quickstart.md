# Quickstart: Brand Kit Interview

## Prerequisites

- Local Supabase is running and migrations are applied.
- `backend/.env` contains the required backend settings and is exported before starting the API.
- Frontend dependencies are installed.

## Manual validation

1. Start the backend:

   ```bash
   set -a
   source backend/.env
   set +a
   make dev-backend
   ```

2. In another terminal, start the frontend with `make dev-frontend`.
3. Sign in and create a brand at `http://localhost:3000/brands`.
4. Open the brand’s **Brand Kit** page from the brand detail screen.
5. Confirm a new kit loads with `not_started` and empty answers.
6. Save one answer, leave the page, return, and confirm the answer remains with `in_progress`.
7. Complete the six questions with 1–3 colors and confirm the summary, `complete` status, and completion time.
8. Edit a required answer to an invalid value and confirm the save is rejected without corrupting the prior valid state.
9. Use two authenticated users to confirm a non-owner receives generic `404 BRAND_NOT_FOUND` for another user’s kit.

## Automated validation

From the repository root:

```bash
backend/.venv/bin/python -m pytest -q backend/tests/contract/test_brand_kits.py
backend/.venv/bin/python -m pytest -q backend/tests/integration/test_brand_kits.py backend/tests/integration/test_brand_kit_rls.py
cd frontend
npm run lint
npx playwright test tests/e2e/brand-kit.spec.ts
npm run build
```

The integration and E2E checks require local Supabase, the API, and the frontend to be running. Provider and image-generation checks are not part of this feature.
