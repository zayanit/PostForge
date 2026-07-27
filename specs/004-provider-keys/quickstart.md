# Quickstart: Validate Provider Keys

Run these scenarios against a real local Supabase instance. The contract tests use mocked provider transports for deterministic error classification; the final provider scenario uses real user-supplied OpenAI and Gemini keys to satisfy the constitution's provider checks.

## Prerequisites

- Local Supabase is running and the Provider Keys migration is applied.
- Backend and frontend are running with the existing runtime configuration.
- Two distinct signed-in accounts exist, each with an owned brand.
- For the real-provider scenario only, have one disposable OpenAI key and one disposable Gemini key. Enter them through the UI; do not place them in source files, command history, screenshots, or test output.

Reference documents:

- API behavior: `contracts/provider-keys.md`
- Schema and state transitions: `data-model.md`
- Security/validation decisions: `research.md`

## Automated Validation Commands

From the repository root, load local Supabase values as for existing integration tests, then run:

```bash
backend/.venv/bin/python -m pytest backend/tests -q
```

From `frontend/`:

```bash
npm run lint
npx tsc --noEmit
npm run build
```

Validate the database schema:

```bash
supabase db lint --level warning
```

Integration tests must execute rather than skip; check the summary and environment if the real-Supabase provider-key/RLS files report skips.

## Scenario 1: Add and list keys without disclosure

1. Sign in as User A and open User A's brand provider-keys page.
2. Add an inactive OpenAI key with a label. Confirm the list shows `***` plus only its final four characters, unvalidated status, and inactive status.
3. Add an active Gemini key. Confirm it is active and the OpenAI key remains unchanged.
4. Reload the page and inspect browser network responses. Confirm neither raw key appears in any response, URL, or error.
5. Inspect `provider_keys` through the privileged local database connection. Confirm records contain only safe metadata and opaque `vault_secret_id` values.
6. As the backend role, resolve each opaque ID through Vault and confirm the stored value matches the submitted credential. Do not print the value; compare within SQL/test assertions.
7. Submit empty, short, unsupported-suffix, invalid-provider, and over-100-character-label requests. Confirm all fail before any Vault secret or provider-key row is created.
8. Add a second active OpenAI key. Confirm the prior OpenAI key becomes inactive atomically and Gemini remains active.
9. Interrupt an add request at commit and retry with the same idempotency UUID. Confirm exactly one Vault secret and one key row exist and the same safe record is returned.

Expected: exactly one active key per provider, multiple inactive historical keys allowed, and no raw credential crosses the client boundary after submission.

## Scenario 2: Validate OpenAI and Gemini classifications

Use deterministic mocked outbound responses first:

1. For each provider, return a documented successful model-list response. Confirm `valid`, a validation timestamp, and no active-state change.
2. Return each provider's explicitly documented invalid credential response. Confirm `invalid`; if the key was active, confirm it is inactive and no replacement activates.
3. Attempt to activate a known-invalid key. Confirm activation is blocked. Then validate it successfully and confirm it becomes eligible but remains inactive until explicitly activated.
4. Return quota, rate-limit, permission, service, malformed, unknown, timeout, and network outcomes. Confirm each is temporary and every persisted validation/active field remains byte-for-byte unchanged.
5. Hold the first validation provider call open and request a second validation for that key. Confirm only one provider request occurs and the second response is temporary `VALIDATION_IN_PROGRESS`.
6. Let a validation lease expire, start a new validation, then release the stale response. Confirm the stale fencing token cannot overwrite the new result.
7. Delay the provider beyond its budget. Confirm the user receives a temporary timeout within 15 seconds.

Then validate real disposable keys through the UI:

8. Validate the known-valid OpenAI key. Require a `valid` result from the official read-only model-list call and confirm no generation occurs. A provider outage blocks this check; it is not a passing temporary result.
9. Validate the known-valid Gemini key. Require the same valid result using the official read-only model-list call and no generation. A provider outage blocks rather than passes the check.
10. Review logs. Confirm only fixed safe event/outcome metadata appears; no key, hint, label, Vault ID, provider body, or authorization header is present.

## Scenario 3: Ownership, RLS, and Vault isolation

1. As User B, call list/add for User A's brand and activate/validate/delete for one of User A's key IDs.
2. Repeat each operation with nonexistent UUIDs. Confirm status, error code, and message match the non-owned case; only request IDs differ.
3. Execute direct SQL as User A's `authenticated` role. Confirm safe-column SELECT can see only User A's records, internal Vault/lease columns are permission-denied, and INSERT/UPDATE/DELETE are permission-denied even for owned rows.
4. Repeat as User B. Confirm safe-column SELECT returns no User A rows and all writes remain permission-denied.
5. Verify catalog privileges show no Vault schema/table/view/function access for `anon` or `authenticated`. In hosted deployments, verify the configured backend database role has exactly the required Vault/application privileges. In local development, the documented `postgres`/superuser exception may have broader privileges, but it must still provide every required Vault/application capability.
6. As `authenticated`, attempt direct reads from `vault.secrets` and `vault.decrypted_secrets`, secret creation, update, and deletion. Require SQLSTATE `42501` rather than an empty result.
7. As both `anon` and `authenticated`, attempt direct SELECT/INSERT/UPDATE/DELETE against `provider_key_idempotency` and `brand_asset_operations`. Require permission denial for every operation, including when the referenced brand is owned by the authenticated user.
8. With a real authenticated JWT, attempt Data API access to both backend-only tables, a `vault` profile, Vault RPCs, and the `private.is_brand_owner` helper RPC. Confirm all are unavailable for both User A and User B while normal owner-scoped metadata reads still exercise the helper through RLS.

Expected: clients cannot retrieve even their own raw key; all Vault access is backend-only, and provider-key metadata remains brand-isolated at API and database layers.

## Scenario 4: Activation and cleanup concurrency

1. Start concurrent activation requests for two OpenAI keys. Confirm both requests settle with exactly one active OpenAI key and no database constraint failure leaks to the client.
2. Race activation with a validation that resolves invalid in both operation orders. Confirm final state is always invalid and inactive.
3. Begin individual key deletion, pause after the cleanup-required fence, and attempt activation/validation. Confirm the key is visible as cleanup-required and both normal operations are blocked.
4. Inject Vault cleanup failure. Confirm deletion is not reported successful, the row remains inactive/cleanup-required, and retry removes both secret and row.
5. Manually remove the Vault secret before retry. Confirm missing-secret cleanup is idempotent and the retained row is removed.
6. Inject a database/decryption outage while retrieving a secret. Confirm `VAULT_UNAVAILABLE` preserves state; separately confirm a successfully detected absent secret commits cleanup-required state.

Expected: cleanup failures always retain a safe owner-visible retry anchor, and successful deletion leaves neither secret nor row.

## Scenario 5: Brand hard delete with provider keys

Brand Kit is not implemented in this phase, so Constitution v2.0.0 marks zero-answer/completed-kit checks N/A. Run this scenario against ordinary brands now; once Brand Kit exists, later features that read or depend on it must add both kit-state variants.

1. Create a brand with a logo, active/inactive OpenAI keys, and active/inactive Gemini keys.
2. Start confirmed brand deletion and pause after the deletion fence. Attempt logo upload, key add, activation, validation, and individual key deletion. Confirm conflicting mutations are blocked.
3. Start a logo upload before deletion fencing and hold it at the Storage boundary. Confirm the durable asset-operation row blocks brand deletion; stale upload completion cannot update a fenced brand and cleanup targets only its own tokenized path.
4. While that asset operation exists, attempt a second upload/removal. Confirm the unique brand operation constraint rejects overlap before any second Storage request.
5. Inject an ambiguous upload timeout/crash. Confirm the operation row becomes unknown/cleanup-required, does not expire based on time or absence polling, and blocks brand deletion until a definitive terminal outcome is supplied by the test/operator recovery path.
6. Inject logo-removal Storage failure. Confirm `logo_path` remains unchanged; ambiguous failure retains a cleanup-required operation, and only definitive reconciliation can remove the exact old tokenized object and clear the row.
7. Replace a logo and fail deletion of the previous tokenized object. Confirm the new logo remains referenced, the operation remains cleanup-required with `previous_path`, and no further mutation or brand deletion succeeds until old-object cleanup is confirmed.
8. Seed legacy and tokenized objects under the brand prefix, then inject Storage failure. Confirm deletion returns `BRAND_CLEANUP_REQUIRED`, the physical brand and all key retry references remain, and no success response is emitted.
9. Retry after Storage recovery. Inject Vault deletion failure. Confirm the Vault transaction rolls back, all key references remain cleanup-required, and the brand remains fenced.
10. Seed more objects than one Storage list/delete batch, retry with all dependencies healthy, and confirm paginated cleanup plus final empty-prefix verification removes the brand row, every object under the prefix, every provider-key/idempotency row, and every referenced Vault secret.
11. Repeat deletion against a brand with no logo and no keys. Confirm clean hard deletion still works.

Expected: successful brand deletion leaves no database row, Vault secret, or Storage asset; every failure is retryable and never masquerades as success.

## Scenario 6: Regression and secrecy review

1. Run all existing auth/profile, container, and Brand CRUD tests.
2. Confirm create/list/detail/logo behavior remains unchanged for active brands.
3. Confirm existing exact-name brand deletion confirmation and opaque not-found behavior remain unchanged.
4. Search backend source/log statements and test captures for raw request keys, authorization headers, Vault decrypted values, provider response bodies, labels, hints, and Vault UUIDs.
5. Confirm SQLAlchemy/httpx debug logging is disabled or redacted and failure tests do not render bound secret parameters in exception text.
6. Confirm direct authenticated deletion of a brand and deletion of an auth user with owned brands cannot bypass the hard-delete coordinator.

Expected: no regression in completed features and no provider credential disclosure through code paths, logs, errors, or tests.
