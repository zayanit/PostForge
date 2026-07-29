# Tasks: Brand Kit Interview

**Feature**: Phase 5 Brand Kit
**Branch**: `006-brand-kit`
**Design inputs**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/brand-kit.md`, `quickstart.md`

## Implementation rules for every task

- Use the existing FastAPI route prefix `/api/v1/brands` and the existing `CurrentUserDep` authentication dependency.
- Use the existing safe error envelope; never return raw SQL errors, access tokens, or another user’s data.
- Use the existing SQLAlchemy text-query store pattern and the existing `BrandStore.lock_owned_brand` ownership check.
- Run the narrowest relevant test after each implementation task. Keep all task checkboxes updated as work completes.

## Phase 1: Setup

- [X] T001 Confirm the working tree is on branch `006-brand-kit` and read `specs/006-brand-kit/contracts/brand-kit.md` before editing implementation files.
- [X] T002 [P] Create the backend test files `backend/tests/contract/test_brand_kits.py`, `backend/tests/unit/test_brand_kit_store.py`, `backend/tests/integration/test_brand_kits.py`, and `backend/tests/integration/test_brand_kit_rls.py` with imports and shared constants matching the existing brand/provider test style; do not implement production behavior yet.
- [X] T003 [P] Create the frontend E2E file `frontend/tests/e2e/brand-kit.spec.ts` with the local app assumptions from `specs/006-brand-kit/quickstart.md`; keep test cases focused on the six-step wizard, partial resume, complete summary, and unauthorized access.

## Phase 2: Foundational backend and database work

**Purpose**: Complete this phase before implementing any user story. It creates the schema, shared models, route registration, and brand-status plumbing used by all stories.

- [X] T004 Create `supabase/migrations/00017_create_brand_kits.sql` with enum types `tone_t` (`formal`, `casual`, `playful`, `professional`, `friendly`) and `kit_status_t` (`not_started`, `in_progress`, `complete`), unless those types already exist; fail the migration if duplicate type creation would be unsafe.
- [X] T005 Add the `brand_kits` table in `supabase/migrations/00017_create_brand_kits.sql` with `brand_id UUID PRIMARY KEY REFERENCES brands(id) ON DELETE CASCADE`, nullable `tagline` (max 160), nullable `tone`, nullable `audience`, `colors TEXT[] NOT NULL DEFAULT '{}'`, nullable `avoid_words`, nullable `summary`, `status` defaulting to `not_started`, nullable `completed_at`, `created_at`, and `updated_at`.
- [X] T006 Add database constraints in `supabase/migrations/00017_create_brand_kits.sql`: audience must be 2–500 trimmed characters when non-null; colors must contain no more than 3 values; every stored color must match the canonical six-digit hexadecimal format `#RRGGBB` (leading `#` required; hex digits are case-insensitive); a complete kit must have a valid tone, audience, and 1–3 colors; an incomplete kit must not retain `completed_at` or `summary`.
- [X] T007 Add the existing `set_updated_at()` trigger, enable and force RLS on `brand_kits`, add an owner-only policy using `private.is_brand_owner(brand_id)`, revoke direct client DML where the repository convention requires it, and grant the backend service role the required DML in `supabase/migrations/00017_create_brand_kits.sql`.
- [X] T008 Add the new table’s SELECT/INSERT/UPDATE/DELETE privilege checks to `_DATABASE_ROLE_PRIVILEGES` in `backend/app/config.py`; preserve the existing vault least-privilege checks and existing table checks.
- [X] T009 [P] Create `backend/app/models/brand_kit.py` with Pydantic models for `BrandKitAnswers`, `BrandKitUpsert`, `BrandKit`, `KitStatus`, and `Tone`; validate trimmed name (2–120), tagline (0–160), audience (2–500 when supplied), tone enum, and colors (0 while partial or 1–3 colors matching the canonical six-digit hexadecimal format `#RRGGBB` (leading `#` required; hex digits are case-insensitive) when complete).
- [X] T010 [P] Add `kit_status: Literal["not_started", "in_progress", "complete"]` to the brand response model in `backend/app/models/brand.py` without removing or renaming any existing brand response fields.
- [X] T011 Update `backend/app/services/brand_store.py` list and get queries to left join `brand_kits`, return `kit_status = 'not_started'` when no kit row exists, and return the stored kit status otherwise; update `_to_brand` and related tests for the new response field.
- [X] T012 [P] Create `backend/app/services/brand_kit_store.py` with dependency factory `get_brand_kit_store`, a service dataclass using the existing engine, deterministic summary derivation, and helper functions that map database rows to the Pydantic response without exposing internal columns.
- [X] T013 Create `backend/app/routes/brand_kits.py` with router prefix `/api/v1/brands`, `GET /{brand_id}/kit`, and `PUT /{brand_id}/kit`; register the router in `backend/app/main.py` and ensure unauthenticated requests still produce `401 UNAUTHORIZED` through `CurrentUserDep`.
- [X] T014 In `backend/app/routes/brand_kits.py`, map a missing or non-owned brand to `404 BRAND_NOT_FOUND`, invalid payloads to the existing `400 VALIDATION_ERROR` handler, cleanup-in-progress to `409 BRAND_CLEANUP_REQUIRED`, and never return a kit row for another owner.

**Foundational checkpoint**: Apply migration `00017`, run the backend contract tests, and verify the API imports successfully before starting user-story implementation.

## Phase 3: User Story 1 — Complete a brand kit (P1, MVP)

**Goal**: An owner can answer all six questions, save a complete kit, see a deterministic summary, and edit it later.

**Independent test**: Create a brand, submit valid answers for name, tagline, tone, audience, 1–3 colors, and avoid words, then GET the kit and verify `complete`, `completed_at`, all answers, and summary content.

### Tests first

- [ ] T015 [P] [US1] Add contract tests in `backend/tests/contract/test_brand_kits.py` for `GET` with no row returning `not_started`, valid `PUT` returning `complete`, optional tagline/avoid-words omission, and response fields matching `contracts/brand-kit.md`.
- [ ] T016 [P] [US1] Add unit tests in `backend/tests/unit/test_brand_kit_store.py` for deterministic summary text containing brand name, tagline, tone, audience, colors, and `None specified` for omitted optional answers.
- [ ] T017 [P] [US1] Add integration coverage in `backend/tests/integration/test_brand_kits.py` for creating a real brand, saving a complete kit, reading it back, editing it, and confirming only one `brand_kits` row exists.

### Implementation

- [ ] T018 [US1] Implement `BrandKitStore.get_kit` in `backend/app/services/brand_kit_store.py`: lock the requested owned brand before reading the kit, return an empty response with `not_started` when no row exists, and return saved answers/status/summary/timestamps when a row exists.
- [ ] T019 [US1] Implement `BrandKitStore.upsert_kit` in `backend/app/services/brand_kit_store.py`: lock the owned brand row, trim and update the existing brand name, preserve omitted answer fields, clear explicitly null/empty fields, validate the resulting answer set, derive status server-side, derive summary only for a valid complete kit, and insert or update by the `brand_id` primary key.
- [ ] T020 [US1] Complete the GET and PUT route handlers in `backend/app/routes/brand_kits.py`, including request logging with only event and request ID fields and response models matching `contracts/brand-kit.md`.
- [ ] T021 [US1] Add the Brand Kit entry point to `frontend/app/(dashboard)/brands/[brandId]/page.tsx`: render a clear link to `/brands/{brandId}/kit`, disable or explain unavailability when the brand is in cleanup, and preserve the existing logo/provider/delete sections.
- [ ] T022 [US1] Create `frontend/app/(dashboard)/brands/[brandId]/kit/page.tsx` with authenticated loading, six ordered steps (Name, Tagline, Tone, Audience, Colors, Avoid words), Previous/Next controls, field labels, inline validation, and a visible current-step indicator.
- [ ] T023 [US1] In `frontend/app/(dashboard)/brands/[brandId]/kit/page.tsx`, submit the full form to `PUT /api/v1/brands/{brand_id}/kit` with the Supabase access token, display API validation errors, disable controls while saving, and display a complete summary after a successful complete response.
- [ ] T024 [US1] Add the complete-kit browser journey to `frontend/tests/e2e/brand-kit.spec.ts`: record a start timestamp, create or select a test brand, fill all six steps with valid values and two colors, submit, assert the summary and complete status within 5 minutes, reload, and assert the values remain.

**US1 checkpoint**: Run these two shell commands separately: `backend/.venv/bin/python -m pytest -q backend/tests/contract/test_brand_kits.py backend/tests/unit/test_brand_kit_store.py` and `backend/.venv/bin/python -m pytest -q backend/tests/integration/test_brand_kits.py`. The complete-kit Playwright test must also pass.

## Phase 4: User Story 2 — Save and resume partial answers (P1)

**Goal**: A kit supports zero answers, partial progress, auto-save after each completed step, explicit save, resume after reload, and optional answers omitted on completion.

**Independent test**: Open a new kit, verify `not_started`, save one step and leave, return and verify `in_progress` with that value, then complete the remaining required fields without tagline or avoid words.

### Tests first

- [ ] T025 [P] [US2] Add contract tests in `backend/tests/contract/test_brand_kits.py` for zero-answer PUT returning `not_started` with null summary/completed_at, at-least-one-answer PUT returning `in_progress`, omitted fields preserving stored values, explicit null/empty fields clearing values, empty colors being accepted while partial, invalid completion being rejected, and repeated PUT not creating a duplicate row.
- [ ] T026 [P] [US2] Add unit tests in `backend/tests/unit/test_brand_kit_store.py` for `not_started`/`in_progress`/`complete` transitions, clearing summary/completed_at when a complete kit becomes incomplete, and last-successful-save-wins transaction behavior.
- [ ] T027 [P] [US2] Add integration tests in `backend/tests/integration/test_brand_kits.py` for partial save/reload, omitted optional answers producing a complete summary with explicit unspecified values, invalid save preserving the prior valid row, and overlapping saves retaining the later committed values.

### Implementation

- [ ] T028 [US2] Extend `BrandKitStore.upsert_kit` in `backend/app/services/brand_kit_store.py` so omitted fields preserve existing values, explicit null/empty fields clear values, partial data is stored as `in_progress`, empty colors are allowed only for incomplete kits, incomplete edits clear `summary` and `completed_at`, and the owned-brand transaction lock provides last-successful-save-wins behavior.
- [ ] T029 [US2] Add explicit `Save progress` and automatic save-on-Next behavior to `frontend/app/(dashboard)/brands/[brandId]/kit/page.tsx`; keep the user on the current page after a partial save and show `Saved`, `Saving...`, or an actionable error state.
- [ ] T030 [US2] Add resume behavior to `frontend/app/(dashboard)/brands/[brandId]/kit/page.tsx`: populate all fields from GET, restore the first incomplete step, allow Previous navigation, and do not overwrite local edits with a stale load response.
- [ ] T031 [US2] Add the partial/resume browser journey to `frontend/tests/e2e/brand-kit.spec.ts`: verify empty `not_started`, save one answer, reload, verify `in_progress`, navigate backward/forward, and complete with optional fields omitted.
- [ ] T032 [US2] Add clear validation messages in `frontend/app/(dashboard)/brands/[brandId]/kit/page.tsx` for blank name, short audience, invalid tone, zero colors on completion, more than three colors, colors not matching the canonical six-digit hexadecimal format `#RRGGBB` (leading `#` required; hex digits case-insensitive), and overlong tagline; prevent network submission when client validation fails.

**US2 checkpoint**: Contract/unit/integration partial-state tests and the partial/resume Playwright test pass; a failed save leaves the previous valid response visible.

## Phase 5: User Story 3 — Keep kits private to their owner (P1)

**Goal**: Only the owning user can read or update a kit; unauthorized users receive generic not-found responses and no kit data.

**Independent test**: Create two users and two brands, then verify owner GET/PUT succeeds while cross-user GET/PUT returns `404 BRAND_NOT_FOUND`; unauthenticated requests return `401`.

### Tests first

- [ ] T033 [P] [US3] Add contract tests in `backend/tests/contract/test_brand_kits.py` for missing authorization, malformed authorization, non-owner GET, non-owner PUT, nonexistent brand, and safe error envelope/code/message.
- [ ] T034 [P] [US3] Add direct RLS tests in `backend/tests/integration/test_brand_kit_rls.py` proving authenticated owner roles can read/write their own row, cannot read/write another user’s row, and cannot insert a row for another user’s brand.
- [ ] T035 [P] [US3] Extend `backend/tests/integration/test_brand_kits.py` to delete a brand and assert its `brand_kits` row is physically removed; also assert cross-user API responses contain no answer, summary, or brand-name data.

### Implementation and verification

- [ ] T036 [US3] Harden `backend/app/services/brand_kit_store.py` so every GET and PUT begins by resolving the brand through the owner-scoped lock and never queries a kit by `brand_id` alone before ownership is established.
- [ ] T037 [US3] Verify `supabase/migrations/00017_create_brand_kits.sql` RLS, forced RLS, owner policy, cascade behavior, and service-role grants against `backend/tests/integration/test_brand_kit_rls.py`; adjust only the migration or privilege assertion if a test exposes a mismatch.
- [ ] T038 [US3] Update `frontend/app/(dashboard)/layout.tsx` and `frontend/app/(dashboard)/brands/page.tsx` to display the derived `kit_status` (`Not started`, `In progress`, or `Complete`) without exposing another user’s brand data.
- [ ] T039 [US3] Add unauthorized and status-indicator coverage to `frontend/tests/e2e/brand-kit.spec.ts`, including redirecting unauthenticated visitors and showing the correct status after empty, partial, and complete saves.

**US3 checkpoint**: API ownership, direct RLS, hard-delete, and frontend status tests pass with generic 404 behavior for non-owners.

## Phase 6: Polish and cross-cutting validation

- [ ] T040 [P] Update `backend/tests/contract/test_brands.py` and any affected brand fixtures to assert the new `kit_status` field without breaking existing brand CRUD behavior.
- [ ] T041 Run `backend/.venv/bin/python -m pytest -q backend/tests/contract/test_brand_kits.py backend/tests/unit/test_brand_kit_store.py backend/tests/contract/test_brands.py` and fix only failures caused by this feature.
- [ ] T042 Run `backend/.venv/bin/python -m pytest -q backend/tests` from the repository root and record the result in `specs/006-brand-kit/quickstart.md`.
- [ ] T043 Run `cd frontend && npm run lint`, `cd frontend && npx playwright test tests/e2e/brand-kit.spec.ts`, and `cd frontend && npm run build`; record exact outcomes in `specs/006-brand-kit/quickstart.md`.
- [ ] T044 Run the complete `specs/006-brand-kit/quickstart.md` manual/API validation sequence against local Supabase and confirm the documented zero-answer, partial, complete, unauthorized, and hard-delete outcomes.
- [ ] T045 Verify the applicable constitution checks in `.specify/memory/constitution.md`: acceptance layers, brand-kit zero/complete cases, RLS/forced RLS/privileges, server ownership, safe logging, and physical kit deletion; document provider/generation checks as N/A because this feature does not call them.
- [ ] T046 Measure owner-scoped kit GET/PUT p95 latency under normal local load using `backend/tests/integration/test_brand_kits.py` or a focused benchmark, and record the measured result against the 500ms goal in `specs/006-brand-kit/quickstart.md`.
- [ ] T047 Run `git diff --check`, review `git status --short`, and ensure `specs/006-brand-kit/tasks.md` has every completed task marked `[x]` before handoff, after T046 is complete.

## Dependencies and execution order

### Phase dependencies

- Phase 1 must finish before Phase 2.
- Phase 2 must finish before any user story because it creates the migration, models, routes, and brand status field.
- US1 is the MVP and should be completed before US2 UI work; US2 extends the same store and wizard.
- US3 tests can be written in parallel with US1/US2, but RLS verification requires the migration from Phase 2 and the implemented store/routes.
- Phase 6 starts only after US1, US2, and US3 checkpoints pass.

### Parallel opportunities

- T002 and T003 can run in parallel.
- T009, T010, and T012 can run in parallel after the migration shape is agreed.
- Within each user story, test-writing tasks marked `[P]` can run in parallel because they edit different test files or independent test sections.
- T015–T017, T025–T027, and T033–T035 can be delegated to separate workers before their corresponding implementation tasks.
- T040 must finish before T041 because both tasks may update `backend/tests/contract/test_brands.py`.

## MVP implementation strategy

1. Complete Phase 1 and Phase 2.
2. Deliver US1 first: schema, owner-scoped GET/PUT, complete-kit summary, and the six-step wizard.
3. Deliver US2: partial state, auto-save, explicit save, resume, and incomplete validation.
4. Deliver US3: direct RLS, cross-user API tests, hard-delete verification, and status navigation.
5. Run all Phase 6 checks and update the task checkboxes/documentation.

## Task format validation

All implementation tasks use `- [ ] T###`, include `[P]` only for independently parallelizable work, include `[US1]`, `[US2]`, or `[US3]` only inside a user-story phase, and name the exact repository path to edit or validate.
