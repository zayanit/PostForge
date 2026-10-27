# Tasks: Image Generation (OpenAI-first release)

**Feature**: Phases 6–7, OpenAI-first
**Branch**: `007-image-generation` (implemented in `64d2a48`; review fixes in PR #24)
**Design inputs**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/generations-api.md`, `contracts/worker.md`, `quickstart.md`

> The original `tasks.md` was a nine-item checklist written alongside the
> implementation; this version restructures it into spec-kit format with the same
> completion state. Phases 1–5 record the implementation commit. Phase 6 records the
> review fixes. Phase 7 holds the release gates, which still require real services or
> credentials.

## Phase 1: Schema and storage

- [X] T001 Create `supabase/migrations/00019_create_generations.sql`: `generations` table with lifecycle, lease, and path constraints; history/queue/recovery indexes.
- [X] T002 Enable and force RLS on `generations`; owner-only SELECT policy for `authenticated`; no client writes; backend DML grants.
- [X] T003 Create the private `generation-assets` bucket (PNG only, 50 MB limit, no client object policies).
- [X] T004 Add `generations` privileges to `_DATABASE_ROLE_PRIVILEGES` in `backend/app/config.py` and document the backend role grants.

## Phase 2: API (User Stories 1, 3, 4)

- [X] T005 [P] Add presets and provider sizes in `backend/app/presets.py` and request/response models in `backend/app/models/generation.py`.
- [X] T006 Implement idempotent submission with brand/kit context and key snapshots in `GenerationStore.submit`.
- [X] T007 Implement paginated, filtered history and detail with signed URLs in `backend/app/routes/generations.py`.
- [X] T008 Implement permanent deletion (fence, storage delete, row delete) with `cleanup_required` retry.
- [X] T009 [P] Implement private-bucket upload, sign, exists, and delete in `backend/app/services/generation_storage.py`.

## Phase 3: Worker (User Story 2)

- [X] T010 Implement atomic claims, lease tokens, renewal, and stale-token fencing in `GenerationStore`.
- [X] T011 Implement the bounded OpenAI call and PNG processing in `backend/app/services/image_generation.py`.
- [X] T012 Implement recovery that publishes stored images or fails jobs without repeating paid calls.
- [X] T013 Fence uploads with `upload_fence_until`; share a per-brand advisory lock between publication and deletion.
- [X] T014 Extend `BrandDeletion` to clear generated assets and wait out uncertain uploads.

## Phase 4: Frontend (User Stories 1–4)

- [X] T015 Add the generator page with idempotent retry and progress recovery.
- [X] T016 Add history with status filter, pagination, previews, downloads, refreshed signed links, and confirmed deletion.
- [X] T017 Add generate/history navigation to the brand page.

## Phase 5: Packaging and verification

- [X] T018 Supervise the worker in `scripts/container-entrypoint.sh`; add the heartbeat check to `scripts/container-healthcheck.sh`.
- [X] T019 Add `make dev-worker`, Pillow and `embedded-postgres` dependencies with lock hashes, Windows instructions, and roadmap updates.
- [X] T020 Verify deterministic provider/storage cases, isolated PostgreSQL concurrency/RLS, container shell lifecycle, browser journeys, mobile layout, lint, types, and build.

## Phase 6: Review fixes (PR #24)

- [X] T021 Worker waits (bounded, non-blocking) for a busy asset lock instead of discarding a completed image.
- [X] T022 Write worker liveness from a database-free task; keep lease renewal alive across transient database errors; update the healthcheck contract.
- [X] T023 Order claims by each brand's oldest claimable job so one brand cannot starve others.
- [X] T024 History polls only in-progress items and reloads once on completion instead of re-signing every image every 2 seconds.
- [X] T025 Cap SQLAlchemy below 2.1 so fresh installs keep the psycopg2 driver used in production.
- [X] T026 Run generation route database calls in the thread pool; history reads use a non-locking ownership check.
- [X] T027 Run containers with `--stop-timeout 300` so the worker can finish its current job on stop; document the platform grace period.
- [X] T028 Add a composition note to the provider prompt stating the size and the share of the canvas that survives the crop.
- [X] T029 Structured worker logs: one `generation.job_finished` line per job and exception class names, via the shared allowlist formatter in `backend/app/log.py`.
- [X] T030 Replace raw browser network errors in the generation UI; tell users a failed submission is safe to retry.
- [X] T031 Return `BRAND_MUTATION_IN_PROGRESS` (not a cleanup error) when brand deletion finds the asset lock busy, without fencing the brand.
- [X] T032 Write the spec-kit artifacts for this feature retroactively and point `.specify/feature.json` at it.
- [X] T033 Fix the formatting of the generation section on the brand page.

## Phase 7: Release gates

- [ ] T034 Verify real Supabase Auth/Vault/Storage integrations with the full existing suite.
- [ ] T035 Build and run the Linux container; verify worker restart, heartbeat health, and stop-timeout behavior under Docker (`quickstart.md`, Container validation).
- [ ] T036 Run a disposable live OpenAI BYOK generation, signed-link expiry, and cleanup (`quickstart.md`, Manual validation).

These gates need runtime services or credentials that were unavailable during implementation. They are not completed checks.

## Deferred (not part of this feature)

- Gemini generation (roadmap 6.4, 6.11) and the history provider filter in the UI (7.8).
- Logo watermarking and logo modes (6.6, 6.12).
- Larger provider sizes to avoid upscaling YouTube Banner.
