---

description: "Task list template for feature implementation"
---

# Tasks: Brand CRUD

**Input**: Design documents from `/specs/003-brand-crud/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: `plan.md`'s Technical Context commits to pytest + httpx contract/integration
tests, matching `001-user-auth-profile`'s established pattern (unlike the pure-infra
`002-dockerization` feature, which used quickstart validation only) — test tasks are
included below.

**Organization**: Tasks are grouped by user story to enable independent implementation
and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Exact file paths are included in each description

## Path Conventions

Existing root-level `backend/`/`frontend/` monorepo layout (no new top-level
directories) — see `plan.md` § Project Structure for the full file list and the two
documented deviations from `docs/implementation-plan.md`'s illustrative tree.

---

## Phase 1: Setup

No dedicated setup tasks — this feature reuses the existing project scaffolding,
dependencies, and structure. (One new backend dependency, `python-multipart`, is
needed for logo upload — it's scoped to User Story 3, where it's actually used, not
listed here.)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The `brands` table and `brand-assets` bucket every user story's
acceptance scenarios run against — must exist before any story can be built or tested

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T001 [P] Create `supabase/migrations/00014_create_brands.sql`: `brands` table, `uq_brands_owner_name_ci` and `idx_brands_owner_created` indexes, `trg_brands_updated_at` trigger, `ENABLE`/`FORCE ROW LEVEL SECURITY` + the four owner-scoped RLS policies, **and** the `GRANT SELECT, INSERT, UPDATE, DELETE` to `authenticated`/`service_role` in the same migration (per `data-model.md` and `research.md` Decision 1 — do not split the grants into a follow-up migration the way `001-user-auth-profile` had to)
- [X] T002 [P] Create `supabase/migrations/00015_create_brand_assets_bucket.sql`: idempotent `insert into storage.buckets (id, name, public) values ('brand-assets', 'brand-assets', true) on conflict do nothing` (per `research.md` Decision 2)
- [X] T003 Apply migrations (`supabase migration up`) and verify the `brands` table and `brand-assets` bucket both exist (depends on T001, T002)

**Checkpoint**: DB schema and storage bucket ready — user story work can now begin

---

## Phase 3: User Story 1 - Create a brand (Priority: P1) 🎯 MVP

**Goal**: A signed-in user can create a brand with a validated, unique name

**Independent Test**: Sign in, create a brand, confirm it exists; duplicate name (any
case) and invalid-length names are both rejected with no brand created

### Implementation for User Story 1

- [ ] T004 [P] [US1] Contract test for `POST /api/v1/brands` in `backend/tests/contract/test_brands.py`: empty/too-long name → 400, duplicate name (any case) → 409, valid name → 201 with expected shape (per `contracts/brands.md`)
- [ ] T005 [US1] Create `backend/app/models/brand.py`: `Brand` response model, `BrandCreate` request model with a `field_validator` on `name` enforcing 2–120 characters after trimming (FR-002) — must match the `brands` table's `CHECK` constraint in `00014_create_brands.sql` exactly, per `contracts/brands.md` and the validator/DB-constraint drift already documented in `CLAUDE.md` for `profile.py`
- [ ] T006 [US1] Create `backend/app/services/brand_store.py`: `BrandStore` dataclass wrapping `get_engine()` (same pattern as `profile_store.py`), `create_brand()` method that surfaces the DB's unique-violation as a distinguishable duplicate-name error (depends on T005)
- [ ] T007 [US1] Create `backend/app/routes/brands.py` with the `POST /api/v1/brands` handler (calls `brand_store.create_brand`, maps validation errors to 400 and duplicate-name to 409 per `contracts/brands.md`); register the router in `backend/app/main.py` (depends on T006)
- [ ] T008 [US1] Integration test in `backend/tests/integration/test_brand_crud.py`: create success, case-insensitive duplicate rejection, name-length validation — against real Supabase (depends on T007)
- [ ] T009 [US1] Frontend: create-brand page `frontend/app/(dashboard)/brands/new/page.tsx` — form posting to `/api/v1/brands`, inline validation/duplicate-name error display, redirect to the new brand's detail page on success (depends on T007)

**Checkpoint**: User Story 1 is fully functional and independently testable — this is the deployable MVP

---

## Phase 4: User Story 2 - View my brands (Priority: P1)

**Goal**: A signed-in user can list all their brands and open any one to see its
details; a brand they don't own is indistinguishable from one that doesn't exist

**Independent Test**: List with 0/1/many brands; open an owned brand; requesting a
non-owned or nonexistent brand ID both produce the identical "not found" response

### Implementation for User Story 2

- [ ] T010 [P] [US2] Contract test for `GET /api/v1/brands` and `GET /api/v1/brands/{id}` in `backend/tests/contract/test_brands.py`: empty list, populated list, 404 for both a non-owned and a nonexistent ID with byte-identical response shape (depends on T005)
- [ ] T011 [US2] Add `list_brands()` and `get_brand()` to `backend/app/services/brand_store.py` — `get_brand()` raises `LookupError` on not-found/not-owned, matching `ProfileStore.get_profile()`'s existing pattern (depends on T006)
- [ ] T012 [US2] Add `GET /api/v1/brands` and `GET /api/v1/brands/{id}` handlers to `backend/app/routes/brands.py` (`LookupError` → 404 `BRAND_NOT_FOUND`) (depends on T011)
- [ ] T013 [US2] Integration test in `backend/tests/integration/test_brand_crud.py`: list with 0/1/many brands, get an owned brand (depends on T012)
- [ ] T014 [US2] Create `backend/tests/integration/test_brand_rls.py`: cross-user isolation for `GET /brands/{id}` (non-owner and nonexistent ID both 404) plus the direct RLS SQL check from `quickstart.md` Scenario 5 (depends on T012)
- [ ] T015 [US2] Frontend: brand list page `frontend/app/(dashboard)/brands/page.tsx` (empty state, populated list, link to create) (depends on T012)
- [ ] T016 [US2] Frontend: brand detail page `frontend/app/(dashboard)/brands/[brandId]/page.tsx` (name, creation date; logo display/upload UI is added by User Story 3) (depends on T012)
- [ ] T017 [US2] Frontend: add a brand selector to the nav in `frontend/app/(dashboard)/layout.tsx` (depends on T015)

**Checkpoint**: User Stories 1 AND 2 both work independently — a user can create and navigate their brands

---

## Phase 5: User Story 3 - Add or remove a brand logo (Priority: P2)

**Goal**: A signed-in user can upload, replace, and remove a logo image for a brand
they own, with server-side type/size validation

**Independent Test**: Upload a valid image, replace it with a different format,
remove it; a non-image file and an oversized file are both rejected without touching
the existing logo

### Implementation for User Story 3

- [ ] T018 [US3] Add `python-multipart` to `backend/requirements.txt` and regenerate `backend/requirements.lock` (`pip-compile --generate-hashes`) — required for FastAPI to parse `multipart/form-data` uploads; keeps the Docker build's `pip install --require-hashes` in sync (see `CLAUDE.md`)
- [ ] T019 [P] [US3] Contract test for `POST`/`DELETE /api/v1/brands/{id}/logo` in `backend/tests/contract/test_brands.py`: unsupported content-type → 400, over 5 MB → 413, valid upload → 200, delete-with-no-logo → 204 (idempotent) (depends on T005)
- [ ] T020 [US3] Create `backend/app/services/brand_storage.py`: `upload_logo()` and `delete_logo()` against the Supabase Storage REST API via `httpx` using the service-role key, matching `routes/auth.py`'s existing httpx-against-Supabase pattern (per `research.md` Decision 3) — takes already-decoded bytes, so it has no dependency on `python-multipart` (that's only needed by the route handler parsing the incoming upload, see T022)
- [ ] T021 [US3] Add `update_logo_path()` to `backend/app/services/brand_store.py` (depends on T006)
- [ ] T022 [US3] Add `POST`/`DELETE /api/v1/brands/{id}/logo` handlers to `backend/app/routes/brands.py`: validate size and the declared content-type server-side, **and** verify the uploaded bytes actually start with the correct magic-byte signature for that type (PNG `\x89PNG\r\n\x1a\n`, JPEG `\xff\xd8\xff`, WebP `RIFF....WEBP`) — reject with `400 UNSUPPORTED_MEDIA_TYPE` if the signature doesn't match before any upload to Storage happens, since a client-supplied `Content-Type` header alone is an unverified claim, not proof (FR-011's "corrupted image" edge case); upload the new object (upsert), update `logo_path`, and only delete the previous logo object if its path differs from the new one — a same-format replacement reuses the same path and MUST NOT trigger a delete, since the object being deleted would be the one just uploaded (per `research.md` Decision 3) (depends on T018, T020, T021)
- [ ] T023 [US3] Integration test in `backend/tests/integration/test_brand_crud.py`: upload, replace with a different format (confirm the old Storage object is gone and the new one is intact), replace with the *same* format (confirm the logo is still readable/intact afterward — this is the case that would silently delete the new upload if the same-path skip in T022 were missing), remove (idempotent), reject bad type/oversized file, reject a corrupted/non-decodable payload sent with a spoofed `image/png` content-type (e.g. a text file renamed with a `.png`-style content-type) — confirm the request is rejected and no object is stored in Supabase Storage (depends on T022)
- [ ] T024 [US3] Extend `backend/tests/integration/test_brand_rls.py`: cross-user isolation for logo upload and delete (depends on T022, T014)
- [ ] T025 [US3] Frontend: add logo upload/remove UI to `frontend/app/(dashboard)/brands/[brandId]/page.tsx` (file input with client-side type/size hint, calls the logo endpoints, displays the current logo) (depends on T022, T016)

**Checkpoint**: User Stories 1, 2, AND 3 all work — brands can be personalized with a logo

---

## Phase 6: User Story 4 - Delete a brand (Priority: P3)

**Goal**: A signed-in user can permanently delete a brand they own, with a
confirmation step that prevents accidental deletion, and its logo asset is cleaned up

**Independent Test**: Delete a brand with a logo and one without; an incorrect
confirmation blocks deletion and leaves the brand untouched; a non-owner's delete
attempt is refused

### Implementation for User Story 4

- [ ] T026 [P] [US4] Contract test for `DELETE /api/v1/brands/{id}` in `backend/tests/contract/test_brands.py`: 204 on success with matching `confirm_name`, 404 for a non-owned/nonexistent brand, 409 `CONFIRMATION_MISMATCH` for a missing or wrong `confirm_name` (no deletion occurs) (depends on T005)
- [ ] T027 [US4] Add `delete_brand()` to `backend/app/services/brand_store.py` (raises `LookupError` on not-found/not-owned, same pattern as `get_brand()`) (depends on T006)
- [ ] T028 [US4] Add the `DELETE /api/v1/brands/{id}` handler to `backend/app/routes/brands.py`: validate the request body's `confirm_name` exactly matches the brand's current name before doing anything else (409 `CONFIRMATION_MISMATCH` on missing/mismatch, per `contracts/brands.md` — this is the actual server-side enforcement of FR-013, not just a UI convenience), then delete the Storage logo object first via `brand_storage.delete_logo()` (best-effort — log and proceed on failure, per `research.md` Decision 3) if `logo_path` is set, then delete the brand row (depends on T020, T027)
- [ ] T029 [US4] Integration test in `backend/tests/integration/test_brand_crud.py`: delete a brand with a logo (confirm both the DB row and the Storage object are gone), delete a brand with no logo (depends on T028)
- [ ] T030 [US4] Extend `backend/tests/integration/test_brand_rls.py`: cross-user delete attempt is refused and the target brand is unaffected (depends on T028, T024)
- [ ] T031 [US4] Frontend: delete flow on `frontend/app/(dashboard)/brands/[brandId]/page.tsx` — type-the-brand-name-to-confirm control that disables the submit button on a mismatch (immediate UX feedback) and sends the typed value as `confirm_name` in the `DELETE` body, where the backend is the actual source of truth (per `contracts/brands.md`); redirects to the brand list on success, shows an error on a 409 (depends on T028, T025)

**Checkpoint**: All four user stories independently functional — feature complete

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verification that spans all user stories

- [ ] T032 [P] Run the full `quickstart.md` validation (all 5 scenarios) end-to-end after all stories are complete — Scenario 1 step 5 specifically verifies SC-003 (list/open responsiveness at ~50 brands, not just trivial scale)
- [ ] T033 [P] Re-verify constitution Security Rules compliance: confirm `backend/app/routes/brands.py`, `brand_store.py`, and `brand_storage.py` log only `request_id`/`event`/`brand_id` — never the Supabase secret key or full request bodies
- [ ] T034 Verify constitution Principle VII (Definition of Done) for this feature: hard delete verified (DB row AND Storage asset removed), RLS tested (non-owner access blocked for every operation, not just read)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: None — no tasks
- **Foundational (Phase 2)**: No dependencies — BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - US1 has no dependency on US2/US3/US4
  - US2 depends only on Foundational (T005's models, created by US1, but US2's own
    tasks — T010–T017 — only need `models/brand.py` to exist, not US1's route/store
    methods; in practice this project builds phases in priority order, so US1 will
    already be done)
  - US3 depends on Foundational; its `update_logo_path()`/route tasks depend on
    `brand_store.py`/`routes/brands.py` already existing (created by US1)
  - US4 depends on Foundational and, for its Storage cleanup step specifically,
    on US3's `brand_storage.py` (T020) already existing — this is a real,
    documented cross-story dependency, not an artificial one: deleting a brand's
    logo on brand-delete only makes sense once logos can exist at all
- **Polish (Phase 7)**: Depends on all four user stories being complete

### Within Each User Story

- Contract tests (if included) before the implementation they exercise
- Models before services; services before routes; routes before frontend pages
- Story complete before moving to the next priority (recommended — US1→US2→US3→US4
  is also the practical build order given the T020/US4 dependency above)

### Parallel Opportunities

- T001, T002 (Foundational) — different migration files, no shared state until T003 applies both
- T004 (US1), T010 (US2), T019 (US3), T026 (US4) — each contract test file addition can be written in parallel with its own story's implementation tasks (different concerns within the same file, or written test-first)
- T015, T016 (US2 frontend pages) — different files, both only depend on T012

---

## Parallel Example: Foundational Phase

```bash
Task: "Create supabase/migrations/00014_create_brands.sql"
Task: "Create supabase/migrations/00015_create_brand_assets_bucket.sql"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (nothing to do)
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Run `quickstart.md` Scenario 1 (create/list/validation
   portions) independently
5. Deploy/demo if ready — a user who can create a brand and see it persist is a
   genuinely usable increment on its own

### Incremental Delivery

1. Complete Foundational → DB/Storage substrate ready
2. Add User Story 1 → validate → this is the MVP
3. Add User Story 2 → validate (brands become navigable, cross-user isolation proven)
4. Add User Story 3 → validate (brands become personalizable with a logo)
5. Add User Story 4 → validate (full CRUD lifecycle, including safe permanent deletion)
6. Each story adds value without breaking the previous ones

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Tests are included per `plan.md`'s commitment to match `001-user-auth-profile`'s
  pytest + httpx contract/integration pattern
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently
- Avoid: vague tasks, same-file conflicts (`brand_store.py` and `routes/brands.py`
  grow incrementally across stories — each addition is a complete, working method/
  handler, not a stub)
