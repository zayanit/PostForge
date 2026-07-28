---

description: "Dependency-ordered implementation tasks for Provider Keys"
---

# Tasks: Provider Keys

**Input**: Design documents from `/specs/004-provider-keys/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Tests are mandatory because `plan.md` commits to pytest, real-Supabase
integration coverage, frontend checks, and focused Playwright coverage, and because
Constitution Principle VII requires direct RLS, backend-only table denial, Vault
isolation, ownership, secrecy, hard-delete, OpenAI, and Gemini verification.

**Organization**: Tasks are grouped by user story. Tests precede the implementation
they exercise and must fail for the expected missing behavior before implementation
starts. Every task names the exact file or files it changes or validates.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it changes different files and does not depend on an incomplete task
- **[Story]**: Maps a task to User Story 1, 2, 3, or 4
- Setup and foundational tasks intentionally have no story label

## Path Conventions

This feature extends the existing root-level `backend/`, `frontend/`, and `supabase/`
monorepo structure. Use the feature-specific paths selected by `plan.md`; do not create
the older illustrative `services/vault.py`, `services/providers/`, `routes/keys.py`, or
`frontend/lib/api.ts` paths from `docs/implementation-plan.md`.

---

## Phase 1: Setup

No dedicated setup tasks. The existing FastAPI, Next.js, SQLAlchemy, `httpx`, pytest,
Playwright, and Supabase infrastructure is reused without a new runtime dependency.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the database security boundary, backend-role requirements,
brand cleanup state, request deadline, and safe logging rules required by every story.

**CRITICAL**: No user story implementation starts until this phase passes against a
real local Supabase instance.

- [X] T001 Create failing schema/security integration tests in `backend/tests/integration/test_provider_key_rls.py` that assert the planned enums, non-exposed `private.is_brand_owner(uuid)` helper and denied authenticated RPC, constraints, indexes, restrictive foreign keys, `ENABLE`/`FORCE RLS`, owner-only safe-column reads, denied authenticated DML and internal-column reads, complete denial of `provider_key_idempotency` and `brand_asset_operations`, exact Vault denial with SQLSTATE `42501`, and required backend-role `BYPASSRLS`/application/Vault privileges from `data-model.md`
- [X] T002 Update failing Brand CRUD/RLS regressions in `backend/tests/integration/test_brand_crud.py` and `backend/tests/integration/test_brand_rls.py` so test cleanup hard-deletes brands before auth users, and direct authenticated brand `INSERT`/`UPDATE`/`DELETE` expects permission denial for owned and non-owned rows after authenticated DML is revoked
- [X] T003 Create `supabase/migrations/00016_create_provider_keys.sql` with `supabase_vault`, `provider_t`, `provider_key_lifecycle_t`, `brand_deletion_state_t`, hardened `private.is_brand_owner(uuid)` in a non-exposed schema with RLS-only caller privileges, irreversible cleanup triggers, the `brands` lifecycle/logo-path/FK/grant changes, `provider_keys`, `provider_key_idempotency`, `brand_asset_operations`, all checks/indexes/triggers/restrictive FKs, `ENABLE`/`FORCE RLS`, safe-column grants, backend-only grants, and exact Vault privilege revocations/grants specified in `data-model.md`
- [X] T004 Apply and statically validate `supabase/migrations/00016_create_provider_keys.sql` with `supabase migration up` and `supabase db lint --level warning`, then run `backend/tests/integration/test_provider_key_rls.py` and confirm its real-Supabase tests execute rather than skip
- [X] T005 [P] Add failing shared contract tests in `backend/tests/contract/test_provider_keys.py` for the 15-second validation deadline context, fixed provider-key/brand cleanup errors, `X-Request-Id` parity, and JSON log allowlisting that excludes submitted bodies, labels, hints, Vault UUIDs, SQL parameters, provider bodies, authorization headers, exception strings, user IDs, and email addresses
- [X] T006 [P] Extend `backend/app/models/brand.py` so every Brand response maps database `deletion_state` to contract field `cleanup_state: normal | cleanup_required` without exposing internal lifecycle fields
- [X] T007 Extend `backend/app/services/brand_store.py` to select/return brand deletion state, lock the owned brand as the canonical first lock, distinguish hidden brands with `LookupError`, reject normal mutations after cleanup starts, detect active `brand_asset_operations`, and expose short transaction primitives used by provider-key and deletion services
- [X] T008 [P] Harden `backend/app/config.py` with `hide_parameters=True`, bounded pool/connect/statement/lock settings, and a startup assertion that rejects client database roles and verifies `BYPASSRLS` or superuser plus the exact application and Vault privileges required by `00016_create_provider_keys.sql`
- [X] T009 Extend `backend/app/main.py` to establish an absolute monotonic deadline at backend entry for the provider-key validation route, invoke the backend database privilege assertion during startup, and allowlist only `provider`, fixed outcome `code`, `duration_ms`, and `provider_request_id` in addition to existing safe log fields
- [X] T010 Extend `backend/app/auth.py` so JWT/JWKS verification consumes only the remaining validation-route budget and uses a bounded JWKS retrieval timeout without changing behavior for non-validation routes
- [X] T011 Extend `backend/app/routes/brands.py` to return the safe Brand cleanup shape, resolve ownership before cleanup conflicts, reject logo/brand mutations with fixed `BRAND_CLEANUP_REQUIRED` or `BRAND_MUTATION_IN_PROGRESS` errors, and preserve existing opaque 404 and exact confirmation-name behavior
- [X] T012 Add real-Supabase regression coverage in `backend/tests/integration/test_brand_crud.py` for active-brand create/list/detail/logo behavior, visible cleanup-required brands, mutation fences, and restrictive auth-user deletion while owned brands remain
- [X] T013 Run the foundational files `backend/tests/contract/test_provider_keys.py`, `backend/tests/integration/test_brand_crud.py`, `backend/tests/integration/test_brand_rls.py`, and `backend/tests/integration/test_provider_key_rls.py`; resolve only feature-related failures before starting User Story 1

**Checkpoint**: The schema, backend privilege boundary, brand fence, validation deadline,
and logging boundary are enforceable before raw credentials enter the system.

---

## Phase 3: User Story 1 - Add and view provider keys (Priority: P1) MVP

**Goal**: An owner can atomically store OpenAI or Gemini credentials in Vault and list
only safe brand-scoped metadata, including idempotent retry after an ambiguous commit.

**Independent Test**: Add active and inactive OpenAI/Gemini keys to an owned brand,
retry an add with the same idempotency UUID, reload the list, and prove that responses,
ordinary rows, browser state, and logs never contain a raw key.

### Tests for User Story 1

- [X] T014 [P] [US1] Extend `backend/tests/contract/test_provider_keys.py` with failing exact-shape tests for `GET /api/v1/brands/{brand_id}/keys` and `POST /api/v1/brands/{brand_id}/keys`: empty/populated lists, default and explicit `make_active`, malformed/missing `Idempotency-Key`, invalid provider/key suffix/length/whitespace/label, label containing the raw key, retired receipt, Vault failure, opaque brand ownership, no provider call, and absence of raw/internal fields
- [X] T015 [P] [US1] Create failing real-Supabase add/list tests in `backend/tests/integration/test_provider_keys.py` for atomic Vault plus metadata creation, exact `***` final-four hints, inactive and per-provider active additions, one-active replacement, persisted safe list ordering, same-idempotency retry returning one row/secret, known rollback, ambiguous commit reconciliation, and retired receipt rejection after fixture-level deletion
- [X] T016 [P] [US1] Extend `backend/tests/integration/test_provider_key_rls.py` with failing API and direct-data tests for owner/non-owner/nonexistent brand list/add parity, safe owner metadata visibility, hidden `brand_id`/Vault/lease/last-used fields, denied same-owner and cross-owner writes, and raw Vault isolation through SQL and Data API

### Implementation for User Story 1

- [X] T017 [P] [US1] Create `backend/app/models/provider_key.py` with provider/lifecycle enums, verbatim raw-key add request validation, optional 100-character label validation that rejects the submitted key, UUID idempotency-header parsing support, and safe key/list response models containing only fields permitted by `contracts/provider-keys.md`
- [X] T018 [US1] Create `backend/app/services/provider_key_store.py` with safe row conversion and list/add methods that lock brand first, reject fenced brands or pending key cleanup, reconcile `provider_key_idempotency`, create the application UUID before `vault.create_secret`, atomically insert Vault secret/receipt/key metadata, atomically replace only the same provider's active key, and map known/ambiguous database outcomes without exposing binds or decrypted values
- [X] T019 [US1] Create `backend/app/routes/provider_keys.py` with dependency aliases and the list/add handlers, fixed safe error mapping, ownership-before-lifecycle ordering, required UUID `Idempotency-Key`, response-model filtering, and fixed safe structured events; register its router in `backend/app/main.py`
- [X] T020 [US1] Create `frontend/app/(dashboard)/brands/[brandId]/keys/page.tsx` with authenticated defensive fetches, OpenAI/Gemini groups, safe key cards, add form, active/inactive/unvalidated/cleanup badges, a client UUID retained for retry of one ambiguous submission, raw-key clearing after success, and no raw key in URLs, errors, or retained visible state
- [X] T021 [P] [US1] Add provider-keys navigation and cleanup-state disabling to `frontend/app/(dashboard)/brands/[brandId]/page.tsx`, and update current-brand path recognition for nested `/brands/{brandId}/keys` routes in `frontend/app/(dashboard)/layout.tsx`
- [X] T022 [US1] Create `frontend/tests/e2e/provider-keys.spec.ts` with a focused add/list/reload flow using disposable test fixtures, assertions for provider grouping and masked hints, and browser request/response checks that the submitted fixture key never reappears
- [X] T023 [US1] Execute Quickstart Scenario 1 from `specs/004-provider-keys/quickstart.md` plus `backend/tests/contract/test_provider_keys.py`, `backend/tests/integration/test_provider_keys.py`, `backend/tests/integration/test_provider_key_rls.py`, and `frontend/tests/e2e/provider-keys.spec.ts`; confirm exactly one Vault secret and key row per idempotency UUID and no skipped security integration tests

**Checkpoint**: User Story 1 is a deployable BYOK setup MVP with no reveal path.

---

## Phase 4: User Story 2 - Validate a provider key (Priority: P1)

**Goal**: Validate through each provider's official read-only models endpoint within the
absolute deadline, classify only documented structured credential rejection as invalid,
and prevent overlapping or stale attempts from changing persisted state.

**Independent Test**: Exercise accepted, documented invalid, ambiguous, permission,
quota, rate-limit, service, malformed, network, timeout, overlapping, and stale outcomes
for both providers and verify only accepted/explicit-invalid outcomes persist changes.

### Tests for User Story 2

- [X] T024 [P] [US2] Create failing `httpx.MockTransport` unit tests in `backend/tests/unit/test_provider_validation.py` for exact official URLs/headers, redirects and retries disabled, structurally valid success, OpenAI `error.code == invalid_api_key`, every allowed Gemini `google.rpc.ErrorInfo.reason`, ambiguous 400/401/403, permission/quota/rate-limit/service/unknown/malformed responses, provider request IDs, network errors, and timeout classification without logging body/header/key data
- [X] T025 [P] [US2] Extend `backend/tests/contract/test_provider_keys.py` with failing exact-shape tests for `POST /api/v1/brands/{brand_id}/keys/{key_id}/validate`: valid/invalid/temporary code matrix, complete safe key snapshot, fixed provider messages, active invalid deactivation, temporary byte-for-byte state preservation, opaque path membership, cleanup conflicts, Vault failure, `VALIDATION_IN_PROGRESS`, `VALIDATION_SUPERSEDED`, and response within the route deadline
- [X] T026 [P] [US2] Extend `backend/tests/integration/test_provider_keys.py` with failing real-Supabase validation lease tests for atomic claim plus Vault decrypt, no connection held during provider I/O, one provider request under overlap, database-clock lease expiry, stale fencing-token rejection, valid persistence, invalid persistence plus deactivation, temporary preservation, absent-secret fencing, and bounded pool/lock/statement failures

### Implementation for User Story 2

- [X] T027 [P] [US2] Create `backend/app/services/provider_validation.py` with injectable async `httpx` transport, official OpenAI and Gemini model-list probes, no redirects/retries, structured provider-specific invalid predicates, fixed valid/invalid/temporary code/message mapping, response-body disposal, provider request-ID extraction, and provider I/O bounded by ten seconds and the remaining route deadline
- [X] T028 [US2] Extend `backend/app/services/provider_key_store.py` with short claim/complete validation transactions: brand-first/key-second locking, lifecycle and brand fences, database-clock lease/token assignment, request-local Vault decryption, `VALIDATION_IN_PROGRESS`, matching-token completion, accepted/invalid persistence, atomic invalid deactivation, stale `VALIDATION_SUPERSEDED`, temporary no-op semantics, and best-effort lease clearing without holding a connection during HTTP
- [X] T029 [US2] Add the validate handler to `backend/app/routes/provider_keys.py`, budget auth/pool/lock/Vault/provider/completion/serialization against the entry deadline, return all completed provider classifications as HTTP 200 outcomes, preserve fixed pre-lease error envelopes, and emit only safe provider/code/duration/request-ID logs
- [X] T030 [US2] Extend `frontend/app/(dashboard)/brands/[brandId]/keys/page.tsx` with explicit validate actions, pending-state deduplication, valid/invalid/unvalidated status and timestamp rendering, fixed temporary outcome feedback, active-key deactivation refresh, and `finally` cleanup for every network path
- [X] T031 [US2] Extend `backend/tests/integration/test_provider_key_rls.py` with owner/non-owner/nonexistent validate parity and assertions that direct clients cannot read or mutate validation tokens, lease expiries, Vault IDs, decrypted values, validity fields, or active state
- [X] T032 [US2] Add deadline and secrecy regression cases to `backend/tests/contract/test_provider_keys.py` that consume budget during authentication, pool checkout, lock/Vault access, provider I/O, and completion; assert every leased request settles within 15 seconds and captured logs/errors omit keys, binds, labels, hints, Vault IDs, provider content, headers, exception text, tokens, and PII
- [X] T033 [US2] Extend `frontend/tests/e2e/provider-keys.spec.ts` with mocked valid, explicit-invalid, temporary, timeout, and already-in-progress UI outcomes, including invalid active-key deactivation and preservation of prior status on temporary outcomes
- [ ] T034 [US2] Execute Quickstart Scenario 2's deterministic steps from `specs/004-provider-keys/quickstart.md` and run `backend/tests/unit/test_provider_validation.py`, the validation cases in `backend/tests/contract/test_provider_keys.py`, `backend/tests/integration/test_provider_keys.py`, and `frontend/tests/e2e/provider-keys.spec.ts`

**Checkpoint**: Both providers validate safely without generation, false invalidation, or
late-result corruption.

---

## Phase 5: User Story 3 - Choose the active key (Priority: P2)

**Goal**: Atomically select at most one active key per brand/provider while blocking
known-invalid or cleanup-required keys and preserving the other provider's selection.

**Independent Test**: Activate between two same-provider keys concurrently, activate a
different provider independently, and race activation against invalid validation; every
terminal state must satisfy the database active-key and invalid-inactive constraints.

### Tests for User Story 3

- [ ] T035 [P] [US3] Extend `backend/tests/contract/test_provider_keys.py` with failing tests for `PATCH /api/v1/brands/{brand_id}/keys/{key_id}/activate`: successful safe shape, unvalidated eligibility, atomic prior deactivation, other-provider preservation, known-invalid block, key/brand cleanup conflicts, opaque path ownership, and no provider call
- [ ] T036 [P] [US3] Extend `backend/tests/integration/test_provider_key_cleanup.py` with failing real-Supabase concurrency tests for simultaneous activation of two same-provider keys, provider-independent activation, activation versus invalid validation in both lock orderings, database unique/check invariants, and safe conflict responses without leaked SQL details

### Implementation for User Story 3

- [ ] T037 [US3] Extend `backend/app/services/provider_key_store.py` with atomic activation that locks brand then target key, rejects fenced/known-invalid targets, deactivates only the current active row for the same provider, activates the target in one transaction, and converts uniqueness races to a fixed safe retry outcome while ensuring no completed ordering leaves an invalid key active
- [ ] T038 [US3] Add the activate handler and fixed `KEY_INVALID`, `KEY_CLEANUP_REQUIRED`, `BRAND_CLEANUP_REQUIRED`, and opaque-not-found mappings to `backend/app/routes/provider_keys.py`
- [ ] T039 [US3] Extend `frontend/app/(dashboard)/brands/[brandId]/keys/page.tsx` with activate controls for eligible inactive keys, disabled controls for invalid/cleanup states, independent provider refresh, fixed conflict feedback, and defensive loading-state cleanup
- [ ] T040 [US3] Execute Quickstart Scenario 4 steps 1-2 from `specs/004-provider-keys/quickstart.md` and run the activation cases in `backend/tests/contract/test_provider_keys.py`, `backend/tests/integration/test_provider_key_cleanup.py`, and `frontend/tests/e2e/provider-keys.spec.ts`

**Checkpoint**: Rotation is atomic, provider-independent, and safe under concurrency.

---

## Phase 6: User Story 4 - Delete provider keys (Priority: P2)

**Goal**: Physically remove individual and brand-wide Vault secrets, key rows, receipts,
and Storage assets while retaining visible inactive retry anchors for every partial or
unknown cleanup outcome.

**Independent Test**: Delete active/inactive keys, inject and retry individual Vault
failures, then delete keyed/logo-bearing brands through Storage and Vault failures;
success must leave no row, secret, receipt, operation, or object under the brand prefix.

### Tests for User Story 4

- [ ] T041 [P] [US4] Extend `backend/tests/contract/test_provider_keys.py` with failing individual-delete tests for active/inactive/cleanup-required keys, 204 only after secret and row absence, retired idempotency receipt, absent-secret idempotency, opaque ownership, brand-cleanup precedence, and fixed 503 `KEY_CLEANUP_REQUIRED` retention
- [ ] T042 [P] [US4] Extend `backend/tests/contract/test_brands.py` with failing cleanup-aware logo and brand-delete tests for durable mutation conflicts, exact confirmation, `BRAND_CLEANUP_REQUIRED`, retry behavior, visible cleanup state, and prohibition of 204 while Storage/Vault/asset-operation cleanup is unresolved
- [ ] T043 [P] [US4] Extend `backend/tests/integration/test_provider_key_cleanup.py` with failing individual cleanup tests for durable inactive fencing before Vault deletion, activation/validation rejection while fenced, Vault rollback, known and ambiguous commit failures, already-absent secret success, receipt retirement, repeated DELETE reconciliation, and no automatic replacement for a deleted active key
- [ ] T044 [P] [US4] Add failing brand hard-delete and asset-operation integration cases to `backend/tests/integration/test_provider_key_cleanup.py` for upload/delete overlap, unique operation ownership, abandoned pending-to-unknown reconciliation, non-expiring unknown outcomes, stale completion, replacement old-object failure, legacy plus tokenized objects, multi-page prefix cleanup, Storage/Vault failure retry, mutation rejection after brand fencing, empty-brand deletion, and final physical absence of all assets/secrets/rows

### Implementation for User Story 4

- [ ] T045 [US4] Extend `backend/app/services/provider_key_store.py` with individual deletion that first commits irreversible cleanup-required/inactive state and clears validation fields/lease, then atomically treats an absent Vault row as clean, deletes the secret and key row, retires idempotency receipts, and retains a safe retry anchor on known or ambiguous cleanup failure
- [ ] T046 [US4] Add the individual DELETE handler to `backend/app/routes/provider_keys.py` with whole-brand-cleanup precedence, fixed 204/404/409/503 behavior, safe retry logs, and no replacement activation
- [ ] T047 [US4] Refactor `backend/app/services/brand_storage.py` to create token-owned `brands/{brand_id}/logos/{operation_id}.{ext}` objects, paginate/list and batch-delete complete prefixes from offset zero, verify final absence, distinguish definitive from unknown remote outcomes, and never clear unknown state from elapsed time or temporary absence
- [ ] T048 [US4] Extend `backend/app/services/brand_store.py` with durable `brand_asset_operations` create/complete/fail/reconcile primitives, one-operation-per-brand enforcement, recorded current/previous paths, stale-token-safe logo updates/removals, abandoned pending-to-unknown fencing, brand deletion fencing, and irreversible transition of all provider keys to cleanup-required/inactive
- [ ] T049 [US4] Create `backend/app/services/brand_deletion.py` to coordinate exact-confirmation ownership lookup, zero-asset-operation precondition, committed brand/key fence, external exhaustive Storage-prefix cleanup without a DB connection, one-transaction Vault/key/receipt cleanup with absent-secret success, final empty-prefix and row verification, and physical brand deletion only after every dependency is absent
- [ ] T050 [US4] Refactor logo upload/removal and confirmed brand deletion in `backend/app/routes/brands.py` to use durable asset operations and `BrandDeletion`, preserve ownership-before-lifecycle ordering, stop treating Storage failure as best effort, and return fixed retryable cleanup/mutation errors without reporting false success
- [ ] T051 [US4] Extend `frontend/app/(dashboard)/brands/[brandId]/keys/page.tsx` with explicit individual deletion, cleanup-required rendering, normal-action disabling, retry DELETE, ambiguous-response relisting, and removal from UI only after confirmed absence
- [ ] T052 [US4] Extend `frontend/app/(dashboard)/brands/[brandId]/page.tsx` with visible brand cleanup state, disabled normal/logo/key navigation mutations, retained exact-name retry deletion, and ambiguous-delete reconciliation before redirect
- [ ] T053 [P] [US4] Extend `frontend/app/(dashboard)/brands/page.tsx` to parse and display `cleanup_state`, keep cleanup-required brands navigable as retry anchors, and distinguish them from normal brands without treating them as deleted
- [ ] T054 [US4] Update `backend/tests/integration/test_brand_crud.py` and `backend/tests/integration/test_brand_rls.py` for tokenized logo paths, no direct authenticated brand writes, hard-delete-only user cleanup, exact owner/non-owner mutation parity, and regression coverage that successful deletion removes the complete Storage prefix
- [ ] T055 [US4] Extend `frontend/tests/e2e/provider-keys.spec.ts` with active/inactive delete, injected cleanup-required retry, disabled normal actions, brand cleanup-state retry, and no automatic replacement assertions
- [ ] T056 [US4] Execute Quickstart Scenarios 4-5 from `specs/004-provider-keys/quickstart.md` and run `backend/tests/contract/test_brands.py`, `backend/tests/contract/test_provider_keys.py`, `backend/tests/integration/test_brand_crud.py`, `backend/tests/integration/test_brand_rls.py`, `backend/tests/integration/test_provider_key_cleanup.py`, and `frontend/tests/e2e/provider-keys.spec.ts`

**Checkpoint**: All key and brand deletion outcomes are either physically complete or
durably retryable; no successful response can leave an untracked secret or asset.

---

## Phase 7: Polish and Cross-Cutting Concerns

**Purpose**: Complete deployment documentation, real-provider checks, regression,
secrecy review, and the phase-aware constitutional Definition of Done.

- [ ] T057 [P] Document in `backend/.env.example` that `DATABASE_URL` must use a private non-client role with forced-RLS bypass and only the required application/Vault privileges, without placing credentials or full example secrets in the file
- [ ] T058 [P] Update `docs/docker.md` with hosted backend-role creation/verification expectations, startup failure troubleshooting, official provider outbound-host requirements, and safe handling of disposable validation keys
- [ ] T059 Run the complete backend suite with `backend/.venv/bin/python -m pytest backend/tests -q` and use `specs/004-provider-keys/quickstart.md` to confirm all provider-key real-Supabase integration files execute rather than skip
- [ ] T060 [P] Run `npm run lint`, `npx tsc --noEmit`, `npm run build`, and `npx playwright test tests/e2e/provider-keys.spec.ts` from `frontend/`; resolve feature-related failures in the changed frontend files
- [ ] T061 [P] Run `supabase db lint --level warning` against `supabase/migrations/00016_create_provider_keys.sql` and re-run the catalog, SQLSTATE, RLS, backend-only table, Data API, and Vault privilege assertions in `backend/tests/integration/test_provider_key_rls.py`
- [ ] T062 Perform the real disposable OpenAI and Gemini checks in Quickstart Scenario 2 steps 8-10 from `specs/004-provider-keys/quickstart.md`; require `valid` from each official model-list endpoint, confirm no generation occurs, and treat provider outage/temporary classification as blocked rather than passed
- [ ] T063 Audit `backend/app`, `backend/tests`, and captured logs using Quickstart Scenario 6 in `specs/004-provider-keys/quickstart.md`; confirm no raw key, label, hint, Vault UUID, decrypted value, authorization header, provider body, SQL bind, token, PII, or secret-bearing exception can cross response/log/test-output boundaries
- [ ] T064 Execute all six end-to-end scenarios in `specs/004-provider-keys/quickstart.md`, including more-than-one-batch Storage cleanup, concurrent activation/validation/deletion, ambiguous commits, missing secrets, and auth-user deletion restrictions, and record any environment-only blocker before claiming completion
- [ ] T065 Verify Constitution v2.0.0 Definition of Done against `specs/004-provider-keys/spec.md` and `specs/004-provider-keys/quickstart.md`: all acceptance layers, direct RLS/privilege tests, server ownership, secrecy/logging, physical DB/Vault/Storage deletion, and real OpenAI/Gemini behavior pass; document Brand Kit and generation/preset/PNG checks as N/A because their prerequisite capabilities do not exist and this feature does not consume them

---

## Dependencies and Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No tasks
- **Foundational (Phase 2)**: Starts immediately and blocks every user story
- **User Story 1 (Phase 3)**: Depends on T001-T013 and delivers the add/list MVP
- **User Story 2 (Phase 4)**: Depends on the saved-key substrate from US1, especially T017-T019
- **User Story 3 (Phase 5)**: Depends on US1's store/route/UI; it may be implemented in parallel with US2 after US1, but T036/T037 must integrate with US2's invalid-completion invariant before final verification
- **User Story 4 (Phase 6)**: Depends on US1's Vault records and receipts, US2's validation leases, US3's active-key transitions, and the foundational brand fence
- **Polish (Phase 7)**: Depends on all selected user stories being complete

### User Story Dependency Graph

```text
Foundational
    |
    v
US1 Add/List (MVP)
    |\
    | +----> US2 Validate ----+
    |                         |
    +------> US3 Activate ----+----> US4 Delete/Cleanup
                                      |
                                      v
                              Polish and full DoD
```

### Within Each User Story

- Write the listed tests first and confirm they fail for the missing behavior
- Add boundary models before stores, stores before routes, and routes before frontend integration
- Never hold a database connection or row lock across provider or Storage I/O
- Always acquire the brand lock before a provider-key lock
- Preserve opaque ownership resolution before lifecycle/conflict errors
- Stop at each checkpoint and run that story's independent tests before continuing

### Parallel Opportunities

- T001, T002, and T005 can be authored in parallel before T003 because they touch separate test concerns
- T006 and T008 can proceed in parallel after the migration contract is understood
- T014-T016 can be authored in parallel; T017 can proceed separately before T018 consumes its models
- T024-T026 can be authored in parallel; T027 can proceed independently of the database lease implementation in T028
- T035 and T036 can be authored in parallel after US1
- T041-T044 can be authored in parallel before deletion/storage implementation starts
- T051 and T053 can proceed in parallel because they modify different frontend pages
- T057, T058, T060, and T061 can run in parallel after implementation stabilizes

---

## Parallel Examples

### User Story 1

```bash
Task: "Write list/add contract tests in backend/tests/contract/test_provider_keys.py"
Task: "Write Vault/idempotency integration tests in backend/tests/integration/test_provider_keys.py"
Task: "Write owner/RLS/Vault denial tests in backend/tests/integration/test_provider_key_rls.py"
```

### User Story 2

```bash
Task: "Write provider classification tests in backend/tests/unit/test_provider_validation.py"
Task: "Write validation API contract tests in backend/tests/contract/test_provider_keys.py"
Task: "Write validation lease tests in backend/tests/integration/test_provider_keys.py"
```

### User Story 3

```bash
Task: "Write activation API tests in backend/tests/contract/test_provider_keys.py"
Task: "Write activation concurrency tests in backend/tests/integration/test_provider_key_cleanup.py"
```

### User Story 4

```bash
Task: "Write individual cleanup contract tests in backend/tests/contract/test_provider_keys.py"
Task: "Write brand cleanup contract tests in backend/tests/contract/test_brands.py"
Task: "Write cleanup concurrency tests in backend/tests/integration/test_provider_key_cleanup.py"
```

---

## Implementation Strategy

### MVP First

1. Complete T001-T013 to establish the security and lifecycle foundation.
2. Complete T014-T023 for User Story 1.
3. Stop and independently validate atomic Vault storage, idempotent add, safe listing,
   RLS, Vault denial, and browser opacity.
4. Deploy only if a brand owner can configure both providers without any reveal path.

### Incremental Delivery

1. Foundational: schema, privilege boundary, brand fence, deadline, and safe logs.
2. US1: add/list keys as the minimum useful BYOK setup.
3. US2: validate both providers without generation or false invalidation.
4. US3: rotate active credentials atomically under concurrency.
5. US4: complete individual and brand-wide retryable physical cleanup.
6. Polish: real-provider verification, full regression, secrecy audit, and DoD.

## Notes

- `[P]` means separate files or non-overlapping work with no dependency on an incomplete task.
- Raw keys may exist only in the add request, request-local backend memory/SQL bind,
  Supabase Vault, and provider authentication header; never add them to fixtures that
  can print on assertion failure.
- A cleanup-required row is a failed-operation retry anchor, not a successful soft delete.
- Missing Vault secrets are idempotent cleanup success; unknown Storage writes remain
  blocked until definitive reconciliation and never expire based only on time.
- No Brand Kit, image generation, provider SDK, key reveal/edit, background cleanup
  worker, pagination for key lists, or new runtime dependency belongs in this feature.
