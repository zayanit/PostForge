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
10. Permanently delete the brand, confirm it disappears from the brand list, and verify its `brands` and `brand_kits` rows no longer exist.

## Automated validation

From the repository root:

```bash
set -a
source backend/.env
set +a
backend/.venv/bin/python -m pytest -q backend/tests/contract/test_brand_kits.py backend/tests/unit/test_brand_kit_store.py backend/tests/contract/test_brands.py
backend/.venv/bin/python -m pytest -q backend/tests/integration/test_brand_kits.py backend/tests/integration/test_brand_kit_rls.py
backend/.venv/bin/python -m pytest -q backend/tests
backend/.venv/bin/python -m backend.tests.integration.benchmark_brand_kits
cd frontend
npm run lint
npx playwright test tests/e2e/brand-kit.spec.ts
npm run build
```

The integration suite and benchmark require local Supabase. Playwright requires the frontend to be running. Provider and image-generation checks are not part of this feature.

## Phase 6 Verification Record

Recorded 2026-07-31:

- T040/T041: The focused Brand Kit and brand-contract command passed with 41 tests.
- T042: The complete backend suite passed with 251 tests.
- T043: Frontend lint and production build passed. The Brand Kit Playwright suite passed all 3 active tests with no skips.
- T044: The real local-Supabase API/data sequence passed with 6 integration tests. It verifies a missing-row `not_started` kit, explicit empty save, partial save/resume, reset to zero answers with row removal, completion, invalid-save rollback, unauthenticated access, generic cross-owner 404 responses, API-triggered brand deletion, and physical kit-row deletion. The Playwright suite verifies the corresponding user-facing wizard, resume, completion, navigation-status, and login-redirect behavior.
- T045: Constitution v2.0.0 checks passed:
  - Acceptance layers: contract/unit tests, real API/database integration tests, and Playwright user-flow tests passed.
  - RLS and privileges: forced RLS, owner policy, authenticated/service-role DML grants, own-row access, and cross-owner read/write denial passed direct integration tests.
  - Ownership and logging: API GET/PUT ownership checks return opaque 404 responses; contract coverage proves success logs contain only event and request ID metadata, excluding tokens, user data, brand names, and answers.
  - Hard deletion: deleting a brand through the API physically removes its Brand Kit row.
  - Brand Kit capability: zero-answer and complete-kit cases passed. Provider and generation checks are N/A because this feature does not call or change those capabilities.
- T046: The reproducible 30-sample local benchmark measured GET p95 at 5.31ms and PUT p95 at 10.75ms, including route-authentication overhead; both are below the 500ms goal.
