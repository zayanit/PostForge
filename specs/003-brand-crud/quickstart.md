# Quickstart: Validate Brand CRUD

Run these scenarios end-to-end against a real local Supabase instance to prove the
feature works, matching the acceptance scenarios in `spec.md`. See
`contracts/brands.md` for exact request/response shapes.

## Prerequisites

- `supabase start` running locally.
- Backend running (`uvicorn app.main:app --reload --port 8000` from `backend/`),
  frontend running (`npm run dev` from `frontend/`).
- Two distinct signed-up user accounts (User A, User B) — reuse the signup flow from
  `specs/001-user-auth-profile/quickstart.md` to create them if needed.

## Scenario 1: Create and list brands (User Story 1 & 2)

1. Sign in as User A. Visit the brand list — expect an empty state, not an error
   (spec US2 Scenario 1).
2. Create a brand named "Acme Coffee". Expect it to appear in the list immediately
   (spec US1 Scenario 1, SC-001).
3. Try creating another brand named "acme coffee" (different case). Expect a clear
   rejection and no second brand created (spec US1 Scenario 2, FR-003).
4. Try creating a brand with an empty name, and one with a 121+ character name.
   Expect both rejected with validation errors (spec US1 Scenario 3, FR-002).
5. Seed ~50 brands for User A (e.g. a small script hitting `POST /api/v1/brands` in
   a loop). Load the brand list and open one of the seeded brands. Expect the list
   to return and the detail page to load without noticeable delay — confirms the
   `idx_brands_owner_created` index (see `data-model.md`) actually serves this query
   at the scale SC-003 targets, not just at trivial (1–3 brand) scale.
5. Open "Acme Coffee" from the list. Expect its name, creation date, and no logo
   shown (spec US2 Scenario 3).

## Scenario 2: Cross-user isolation (User Story 2, FR-006/FR-007)

1. While signed in as User B, attempt to fetch User A's brand by its ID directly
   (e.g. via `GET /api/v1/brands/{User A's brand id}`).
2. Expect a `404 BRAND_NOT_FOUND` — identical to the response for a made-up,
   nonexistent brand ID. Confirm the two responses are byte-for-byte identical
   (status code, error code, message shape) so brand existence is never leaked.
3. Repeat for logo upload, logo delete, and brand delete against User A's brand
   while signed in as User B — all must return the same `404`, and User A's brand
   must be unaffected afterward.

## Scenario 3: Logo upload, replace, and remove (User Story 3)

1. As User A, upload a valid PNG as "Acme Coffee"'s logo. Expect the brand to now
   show that image (spec US3 Scenario 1).
2. Upload a different-format image (e.g. JPEG) as a replacement. Expect only the new
   logo to be visible afterward — inspect Storage directly to confirm the old
   object (different path/extension) is gone, not just unreferenced (spec US3
   Scenario 2, FR-010).
3. Try uploading a non-image file (e.g. a `.txt`). Expect rejection and the existing
   logo unchanged (spec US3 Scenario 4, FR-011).
4. Try uploading an image over 5 MB. Expect rejection with a clear size-limit
   message and the existing logo unchanged (FR-011, per spec Clarifications).
5. Remove the logo. Expect the brand to show no logo afterward (spec US3
   Scenario 3). Remove it again — expect a clean success, not an error (idempotent
   per `contracts/brands.md`).

## Scenario 4: Delete a brand (User Story 4)

1. Create a brand with a logo. Delete it, correctly re-typing its exact name to
   confirm. Expect the brand to disappear from the list, and its logo object to be
   gone from Storage (spec US4 Scenario 1, FR-014; SC-004).
2. Create another brand. Start the delete flow but type the wrong name in the
   confirmation step. Expect the deletion to be blocked and the brand to remain
   exactly as it was (spec US4 Scenario 2, FR-013; SC-006).
3. Create a brand with no logo and delete it. Expect deletion to succeed cleanly
   (spec US4 Scenario 3, FR-015).

## Scenario 5: RLS enforcement at the database layer

Mirroring `specs/001-user-auth-profile/quickstart.md`'s RLS verification approach —
confirm the database itself enforces isolation, not just the API layer:

```sql
-- As User A
SET request.jwt.claims = '{"sub": "user-a-id"}';
SELECT * FROM brands; -- only User A's brands

-- As User B
SET request.jwt.claims = '{"sub": "user-b-id"}';
SELECT * FROM brands WHERE id = 'user-a-brand-id'; -- 0 rows
```
