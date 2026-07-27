# Phase 0 Research: Provider Keys

All specification clarifications are resolved. This research records the implementation decisions needed to fit provider-key management into the existing PostForge architecture without weakening key secrecy, brand isolation, or hard-delete guarantees.

## Decision 1: Access Vault through the existing PostgreSQL connection

**Decision**: Use Supabase Vault's SQL interface through the existing SQLAlchemy engine. Create secrets with `vault.create_secret(...)`, read only `decrypted_secret` from `vault.decrypted_secrets`, and delete from `vault.secrets` with `DELETE ... RETURNING`. Execute Vault changes and `provider_keys` changes on the same connection and transaction. Add-key requests carry a client UUID stored in a safe brand-scoped idempotency receipt committed with the key. Retry after an ambiguous commit returns the committed safe record; deletion retires the receipt so a delayed retry cannot recreate the key.

**Rationale**: Vault is implemented inside the same PostgreSQL database, not as a separate remote secret service. A transaction that creates a Vault secret and inserts its opaque UUID into `provider_keys` either commits both or rolls back both. The same applies to deleting a secret and its record. This is smaller and stronger than a cross-service compensation workflow and directly satisfies FR-004, FR-016, FR-025, and the constitution's Vault rule.

An already-absent Vault row counts as successful idempotent cleanup. After any ambiguous key/brand delete response, clients reconcile by safe list/get before retrying. The backend selects only `decrypted_secret`, keeps it in request-local memory, and never includes it in logs, exceptions, response models, Vault names, or descriptions.

**Alternatives considered**:

- Separate REST/RPC calls for Vault and application records: rejected because independent commits create an avoidable orphan-secret window.
- A different secret manager: forbidden by the constitution's Supabase Vault requirement.
- Storing encrypted key text in `provider_keys`: forbidden because ordinary records may contain only an opaque Vault reference.

## Decision 2: Deny all client access to Vault; apply RLS to application records

**Decision**: Keep the `vault` schema outside PostgREST's exposed schemas and explicitly revoke schema, table/view, and exact-signature function privileges from `PUBLIC`, `anon`, and `authenticated`. Place the `SECURITY DEFINER` ownership helper in a separate non-exposed `private` schema; grant authenticated callers only schema `USAGE` and exact helper `EXECUTE` so RLS can invoke it without publishing a Data API RPC. Only the backend's privileged database role may create, decrypt, or delete Vault secrets. Apply `ENABLE` and `FORCE ROW LEVEL SECURITY` to `provider_keys`; grant authenticated users safe-column SELECT only and no direct DML. The actual `DATABASE_URL` role must pass startup/integration privilege assertions for required Vault/application operations.

**Rationale**: Vault's decrypted view is global and is protected by object privileges rather than tenant RLS. Granting an authenticated client access would expose every secret. Full table DML would also let an owner read `vault_secret_id`, forge lifecycle state, or delete the only retry reference without Vault cleanup. Safe owner metadata reads exercise RLS, while all writes remain backend-mediated. Integration tests prove safe-column visibility, same-owner and cross-owner write denial, SQLSTATE `42501` for Vault, and Data API rejection.

**Alternatives considered**:

- Tenant RLS policies on extension-owned Vault tables/views: rejected because Vault has no brand ownership columns, and altering extension internals complicates upgrades.
- Relying only on default Vault grants: rejected; exact revokes and catalog/startup assertions prevent configuration drift.

## Decision 3: Use one provider-key table for normal and cleanup-required records

**Decision**: Represent the specification's logical Secret Cleanup Reference as a retained `provider_keys` row with `lifecycle = 'cleanup_required'`, not as a separate table. A cleanup-required row is inactive, cannot be validated or activated, remains owner-visible, and is removed only after its Vault secret is confirmed absent.

Creation does not need a staged cleanup row: `vault.create_secret()` and the normal row insert are atomic in one transaction. Individual deletion first commits the cleanup-required/inactive state, then a second transaction atomically deletes the Vault row and provider-key row. This first state transition is the durable retry anchor if the cleanup transaction cannot begin or commit unambiguously.

**Rationale**: One table gives cleanup records the same safe response shape, ownership, RLS, brand relationship, and hard-delete path as normal keys. It avoids duplicating policies and serializers. Atomic creation means the spec's record-creation compensation edge case cannot leave a committed untracked secret.

**Alternatives considered**:

- A `provider_secret_cleanup_refs` table: valid but adds a second RLS policy set, response type, and state machine without improving atomic Vault cleanup.
- Delete the application row before Vault cleanup: rejected because a failed Vault delete would orphan the credential.
- Treat cleanup state as completed deletion: rejected as soft deletion; successful deletion always physically removes the row.

## Decision 4: Coordinate operations with brand-row locks and database constraints

**Decision**: Use the owned `brands` row as the canonical lock. Every key mutation locks brand first, then key, in that order. Add a brand `deletion_state` (`active` or `cleanup_required`) that fences key and asset mutations after brand cleanup starts. Enforce final invariants with database checks and a partial unique index allowing at most one active key per `(brand_id, provider)`.

Activation runs in one short transaction: lock brand/key, reject invalid or cleanup-required targets, deactivate the prior active key for that provider, then activate the target. Invalid validation completion atomically records invalid status and deactivates the key. Constraints reject any committed invalid-active or cleanup-required-active row.

**Rationale**: Row locks already fit the repository's raw SQL transaction pattern and serialize brand deletion against new key creation. Database constraints remain authoritative under concurrency or unexpected writers. One lock order prevents deadlocks; serializing the small number of key mutations per brand is acceptable at MVP scale.

**Alternatives considered**:

- Application-only pre-checks: rejected because concurrent activations can race.
- Advisory locks: unnecessary while every operation has a real brand row to lock, and easier to omit accidentally.
- Holding locks during provider HTTP calls: rejected because it ties up a database connection for up to 15 seconds.

## Decision 5: Use a persisted validation lease and fencing token

**Decision**: Claim validation in a short transaction by locking brand/key, rejecting blocked lifecycle states, and setting a random `validation_token` plus database-clock lease expiry. Retrieve the Vault secret in that transaction, commit, call the provider without a database lock, then complete in another short transaction only if the token still matches. An unexpired lease produces the temporary `VALIDATION_IN_PROGRESS` outcome.

Request middleware establishes the absolute 15-second monotonic deadline before authentication dependencies run. JWT/JWKS verification, threadpool scheduling, database pool checkout, lock/statement execution, Vault lookup, provider I/O, completion write, and response construction all receive only the remaining budget. JWKS retrieval and database pool/lock/statement timeouts are explicitly bounded (normally no more than two seconds per database phase); the provider receives at most 10 seconds and only the time still remaining. Automatic retries are disabled. Temporary outcomes preserve all validation and active fields; the lease is cleared when possible or expires naturally. A stale completion cannot overwrite a later attempt.

**Rationale**: A database lease works across workers and restarts without holding a connection through network I/O. The token fences late responses, while the expiry makes crashes self-healing.

**Alternatives considered**:

- In-memory mutex: rejected because it fails across processes and restarts.
- Database lock held through validation: rejected due connection contention and poor cancellation behavior.
- Apply results in completion order without fencing: rejected because a stale response could overwrite newer state.

## Decision 6: Validate OpenAI with the official model-list operation

**Decision**: Call `GET https://api.openai.com/v1/models` with the key in the bearer authorization header, using the existing `httpx` dependency. Do not send organization/project headers and do not generate content. Disable redirects and retries.

A successful documented response is valid. Invalid requires the canonical JSON fixture predicate `error.code == "invalid_api_key"`; the implementation accepts no message-only or status-only invalid mapping. Generic or ambiguous `401`, all `403`, quota/rate-limit responses, unexpected statuses, malformed responses, network failures, and service failures are temporary. Provider response bodies are parsed in memory only and never logged or returned. If OpenAI changes the structured contract, the unknown response remains temporary until fixtures and mapping are deliberately updated.

**Rationale**: Model listing is official, read-only, and does not consume generation quota. OpenAI has no general API-key introspection endpoint. Model retrieval or image generation introduces model availability, cost, and permission failure modes. Status code alone is insufficient because OpenAI documents permission, organization, and allowlist failures that overlap authentication statuses.

**Alternatives considered**:

- Retrieve a named model: rejected because model availability and retirement can produce unrelated failures.
- Generate a minimal image or other content: rejected by FR-022 and because it incurs cost/quota.
- OpenAI SDK: unnecessary; direct `httpx` gives explicit timeout, redirect, retry, and error-body control with no new dependency.

## Decision 7: Validate Gemini with the official model-list operation

**Decision**: Call `GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=1` with the key in `x-goog-api-key`, using `httpx`, redirects disabled, and no retries. A structurally valid `200` response is valid. Only documented machine-readable credential reasons (`API_KEY_INVALID`, `API_KEY_EXPIRED`, `API_KEY_NOT_FOUND`, and credential-specific `INVALID_CREDENTIAL`) are invalid.

The implementation searches `error.details` for an object whose `@type` is `type.googleapis.com/google.rpc.ErrorInfo` and whose `reason` is one of the allowed credential reasons; status or message alone never marks invalid. All other responses, including generic `400`/`401`, `403` permission failures, quota/rate limits, service errors, unknown reason codes, parse failures, and network failures are temporary. Classification uses structured error details, never mutable human-readable message text.

**Rationale**: Listing one model is a narrow, official, read-only operation with no inference or token cost and no dependency on a specific model. Google explicitly recommends a header rather than a query parameter to reduce key leakage. Machine-readable error reasons provide a safer provider-specific mapping than HTTP status alone.

**Alternatives considered**:

- Retrieve one named model: rejected because model lifecycle and access can create false failures.
- `countTokens` or `generateContent`: broader, model-dependent, and generation can consume quota.
- Put the key in the URL query string: rejected because URLs are more likely to be logged or scanned.

## Decision 8: Brand deletion becomes a retryable hard-delete coordinator

**Decision**: Extend brand deletion into three stages. First, lock the owned brand, verify confirmation, require zero durable asset-operation rows, set `deletion_state = 'cleanup_required'`, mark keys cleanup-required/inactive, and commit the fence. Second, exhaustively remove every object under `brands/{brand_id}/` outside a database transaction; absence is success and failure retains the fenced brand. Third, in one database transaction delete all referenced Vault secrets, delete provider-key and idempotency rows, verify none remain, and hard-delete the brand.

Logo upload/removal is upgraded to create a backend-only durable `brand_asset_operations` row before Storage I/O. A unique brand constraint permits one asset operation at a time. Every upload writes a token-owned path (`brands/{brand_id}/logos/{operation_id}.{ext}`), never a shared filename. Completion updates `logo_path` only while the operation row still owns completion and the brand remains active; stale compensation targets only its own path. Operation rows never expire automatically. Brand deletion cannot fence while any operation row exists, and after fencing it lists/deletes the complete `brands/{brand_id}/` prefix, including legacy and tokenized paths, rather than trusting only `logo_path`.

Prefix cleanup repeatedly lists the first page (bounded page size) under the fenced prefix, deletes returned object names in Storage-supported batches, and repeats from offset zero until empty. Because all brand asset mutation is fenced, the set can only shrink. A final empty-prefix verification is required immediately before database hard delete; any list/delete/verification failure retains the brand and returns cleanup-required.

Logo removal captures the current path in its operation row, deletes that exact object first, and clears `logo_path` only while completing the same operation. On definitive Storage failure it preserves `logo_path` and returns a retryable error. On ambiguous timeout/crash it retains `cleanup_required` with unknown remote status. A stale removal cannot clear a newer database path. Missing objects are success only after the original request has a definitive terminal outcome.

Upload ambiguity follows the same fail-closed rule: retain the operation row and never infer terminal failure from elapsed time or absence polling. Startup/request-time reconciliation marks abandoned pending operations unknown/cleanup-required. If the remote terminal outcome cannot be established, operator recovery is required and brand deletion remains blocked. This trades availability for the constitution's hard-delete guarantee; no `204` is emitted while a late write is possible.

Successful replacement also retains the operation row until its recorded previous path is deleted and confirmed absent. Thus normal replacement cannot accumulate an untracked old object.

**Rationale**: The current brand route logs Storage failure and still deletes the row, and current upload/delete ordering can race with deletion or lose the only path reference. Durable non-expiring operation rows, token-owned paths, and exhaustive prefix cleanup close the late-commit race and keep ambiguous external writes retryable. The fence fixes the cleanup set; retaining the physical brand row is a failed operation retry anchor, not soft deletion. Successful deletion leaves no brand, operation row, key record, Vault secret, or logo.

**Alternatives considered**:

- Continue after Vault or Storage cleanup failure: rejected because success could leave assets or credentials behind without a retry reference.
- Hold a database transaction during Storage calls: rejected because Storage is external to PostgreSQL and network waits must not retain locks/connections.
- Background worker retries: out of scope and unnecessary for user-triggered idempotent retry in MVP.

## Decision 9: Fail closed on database-role and logging configuration

**Decision**: Configure the shared SQLAlchemy engine with hidden bind parameters and bounded pool/connect timeouts. At startup/integration time, assert that the `DATABASE_URL` role has required application DML plus Vault usage/create/decrypt/delete privileges and is not an `anon`/`authenticated` client role. Extend the JSON log formatter's explicit allowlist only with safe fields (`provider`, fixed outcome code, duration, provider request ID); never log labels, hints, Vault UUIDs, SQL parameters, outbound headers, provider bodies, or exception strings from secret-bearing operations.

Local development may use the local privileged `postgres` login. Hosted deployment must supply a private backend-only role with `BYPASSRLS` (table ownership alone does not bypass forced RLS), required application DML, and only the Vault privileges used here (`create_secret`, decrypted `id`/value SELECT, and secret `id` SELECT/DELETE). Browser/service configuration never receives `DATABASE_URL`; startup checks reject client roles or a role that forced RLS would block.

**Rationale**: `SUPABASE_SECRET_KEY` does not determine the PostgreSQL login used by SQLAlchemy. Explicit privilege checks avoid silently deploying with a role that cannot use Vault or one intended for clients. SQLAlchemy exceptions can render bind values unless parameter hiding is enabled, and the current formatter drops fields outside its allowlist.

**Alternatives considered**:

- Assume `DATABASE_URL` always uses `postgres`: rejected as an undocumented production security/deployment dependency.
- Log full exceptions/provider bodies for diagnostics: rejected because they may echo credentials or authentication headers.
- Enable broad structured-log extras: rejected; an allowlist is easier to audit and test.

## Sources

- Supabase Vault: https://supabase.com/docs/guides/database/vault
- Supabase Vault SQL definitions: https://github.com/supabase/vault
- Supabase Row Level Security: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase custom schema exposure: https://supabase.com/docs/guides/api/using-custom-schemas
- OpenAI model listing: https://platform.openai.com/docs/api-reference/models/list
- OpenAI authentication and errors: https://platform.openai.com/docs/api-reference/authentication and https://platform.openai.com/docs/guides/error-codes
- Gemini model listing: https://ai.google.dev/api/rest/v1beta/models/list
- Gemini API key security and errors: https://ai.google.dev/gemini-api/docs/api-key and https://ai.google.dev/gemini-api/docs/troubleshooting#error-codes
- Google API error model: https://google.aip.dev/193
