# Contract: Provider Keys API

All endpoints require `Authorization: Bearer <supabase_access_token>` and are scoped to a brand owned by the authenticated user. Raw provider keys may exist only in the add-key request body, backend request-local memory/bound transaction parameter, Supabase Vault, and the backend's server-to-provider authentication header (OpenAI bearer header or Gemini `x-goog-api-key`). They never appear in URLs, client-facing headers, responses, errors, logs, or ordinary database records.

Errors use the existing envelope:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable safe message.",
    "request_id": "uuid"
  }
}
```

A non-owned brand/key and a nonexistent brand/key return the same `404` code and message for well-formed requests. Framework-level malformed path/body validation returns the same `400` regardless of ownership and performs no mutation. Validation provider bodies and Vault identifiers are never forwarded. Every error response includes `X-Request-Id` equal to `error.request_id`. For well-formed resource requests, ownership/path membership is resolved before lifecycle or brand-cleanup checks, so hidden resources return opaque `404` rather than a revealing `409`.

## Safe Provider-Key Shape

```json
{
  "id": "uuid",
  "provider": "openai",
  "label": "Production Key",
  "key_hint": "***A1B2",
  "is_active": true,
  "is_valid": true,
  "last_validated_at": "2026-07-26T12:00:00Z",
  "last_validation_error": null,
  "cleanup_state": "normal",
  "created_at": "2026-07-26T11:00:00Z"
}
```

Rules:

- `provider` is `openai` or `gemini`.
- `key_hint` is exactly `***` plus the submitted key's final four characters.
- `is_valid` is `null` until a valid or invalid validation completes.
- `last_validated_at` and `last_validation_error` are `null` while unvalidated. A valid result has a timestamp and null error. An invalid result has a timestamp and safe `INVALID_CREDENTIAL` error.
- `cleanup_state` is `normal` or `cleanup_required`.
- Cleanup-required rows keep this stable field set, always have `is_active: false`, and use `null` for all validation fields; no field is omitted and no Vault identifier is exposed.

## `GET /api/v1/brands/{brand_id}/keys`

List all normal and cleanup-required provider-key records for the owned brand, grouped client-side by provider and ordered newest-first within each provider.

**Response `200`**:

```json
{
  "keys": [
    {
      "id": "uuid",
      "provider": "openai",
      "label": "Production Key",
      "key_hint": "***A1B2",
      "is_active": true,
      "is_valid": null,
      "last_validated_at": null,
      "last_validation_error": null,
      "cleanup_state": "normal",
      "created_at": "2026-07-26T11:00:00Z"
    }
  ]
}
```

An owned brand with no keys returns `{"keys": []}`.

**Errors**:

- `404 BRAND_NOT_FOUND` - brand is nonexistent or not owned by the caller.

## `POST /api/v1/brands/{brand_id}/keys`

Add a provider key. Vault creation and application-row creation commit atomically.

**Required header**: `Idempotency-Key: <client-generated UUID>`. Reusing the same UUID for the same owned brand returns the originally committed safe record and never creates another Vault secret. If that key was subsequently deleted, reuse returns `409 IDEMPOTENCY_KEY_RETIRED` and does not recreate it. A malformed UUID returns `400 VALIDATION_ERROR`.

**Request**:

```json
{
  "provider": "openai",
  "key": "provider-secret-value-A1B2",
  "label": "Production Key",
  "make_active": true
}
```

- `provider` is required and limited to `openai` or `gemini`.
- `key` is required, non-whitespace, at least five characters, and must end in four letters, digits, underscores, or hyphens. It is treated verbatim and never normalized.
- `label` is optional, nullable, and at most 100 characters. It is rejected if it contains the submitted raw key.
- `make_active` is optional and defaults to `true`. `false` stores an inactive key even when no active key exists.

**Response `201`**: safe provider-key shape. A newly added key is unvalidated (`is_valid: null`). Adding a key never calls a provider.

When `make_active` is true, activation and deactivation of the previous key for that provider are part of the same database transaction.

**Errors**:

- `400 VALIDATION_ERROR` - invalid provider, key boundary, or label.
- `404 BRAND_NOT_FOUND` - brand is nonexistent or not owned.
- `409 BRAND_CLEANUP_REQUIRED` - brand deletion cleanup is pending; no Vault secret or row is created.
- `409 IDEMPOTENCY_KEY_RETIRED` - this add request previously succeeded and its key was later deleted; use a new UUID for a deliberate new key.
- `502 VAULT_UNAVAILABLE` - the transaction is known not to have committed. If connection loss makes commit outcome unknown, the client retries with the same `Idempotency-Key`; the server returns the committed record or safely performs the transaction once.

## `PATCH /api/v1/brands/{brand_id}/keys/{key_id}/activate`

Activate one key and atomically deactivate the prior active key for the same brand/provider. No request body.

**Response `200`**: updated safe provider-key shape.

**Errors**:

- `404 PROVIDER_KEY_NOT_FOUND` - brand/key is nonexistent, key is outside the path brand, or either belongs to another user. Message: `Provider key not found.`
- `409 KEY_INVALID` - key is known invalid and must validate successfully before activation.
- `409 KEY_CLEANUP_REQUIRED` - key cleanup is pending.
- `409 BRAND_CLEANUP_REQUIRED` - brand cleanup is pending.

An unvalidated key is eligible for activation. Activating one provider never changes the other provider's active key.

## `POST /api/v1/brands/{brand_id}/keys/{key_id}/validate`

Validate a normal key with its provider's official read-only model-list operation. No request body. The 15-second route deadline starts at backend entry and applies to ownership lookup, pool/lock acquisition, Vault access, provider I/O, completion, and response construction. Authentication, malformed input, hidden resources, lifecycle blocks, or infrastructure failure before a validation lease commits use the safe error envelope; every request with a committed lease returns a validation outcome within the same deadline.

**Response `200`**:

```json
{
  "outcome": "valid",
  "attempted_at": "2026-07-26T12:00:00Z",
  "code": "VALID",
  "message": "OpenAI accepted this API key.",
  "key": {
    "id": "uuid",
    "provider": "openai",
    "label": "Production Key",
    "key_hint": "***A1B2",
    "is_active": true,
    "is_valid": true,
    "last_validated_at": "2026-07-26T12:00:00Z",
    "last_validation_error": null,
    "cleanup_state": "normal",
    "created_at": "2026-07-26T11:00:00Z"
  }
}
```

`outcome` is `valid`, `invalid`, or `temporary`. All three classifications return this `200` response shape rather than the error envelope. `attempted_at` is the current request time, including `VALIDATION_IN_PROGRESS` when no second provider call occurs. `key` is always the latest safe snapshot loaded for the owned path key; temporary outcomes preserve its persisted validation and active fields byte-for-byte.

Examples of the outcome-specific fields (the `key` field always follows the safe shape above):

```json
{"outcome":"valid","attempted_at":"2026-07-26T12:00:00Z","code":"VALID","message":"OpenAI accepted this API key.","key":{}}
```

```json
{"outcome":"invalid","attempted_at":"2026-07-26T12:00:00Z","code":"INVALID_CREDENTIAL","message":"OpenAI rejected this API key.","key":{}}
```

```json
{"outcome":"temporary","attempted_at":"2026-07-26T12:00:00Z","code":"PROVIDER_UNAVAILABLE","message":"OpenAI could not validate the key right now.","key":{}}
```

The abbreviated `{}` in these examples denotes the complete safe key object already defined; implementations do not return a partial object.

| Outcome | Allowed safe codes | Persisted effect |
|---|---|---|
| `valid` | `VALID` | Set valid and validation time; preserve active state |
| `invalid` | `INVALID_CREDENTIAL` | Set invalid/time/safe error and deactivate; activate no replacement |
| `temporary` | `PROVIDER_TIMEOUT`, `PROVIDER_UNAVAILABLE`, `PROVIDER_RATE_LIMITED`, `PROVIDER_PERMISSION`, `VALIDATION_UNDETERMINED`, `VALIDATION_IN_PROGRESS`, `VALIDATION_SUPERSEDED` | Preserve validation and active state |

No outcome/code combination outside this table is valid. A structurally valid documented `2xx` model-list response maps to `VALID`. Network/service failure maps to `PROVIDER_UNAVAILABLE`; provider deadline to `PROVIDER_TIMEOUT`; `429` to `PROVIDER_RATE_LIMITED`; permission/precondition responses to `PROVIDER_PERMISSION`; malformed, unknown, and all other unmapped responses to `VALIDATION_UNDETERMINED`; an unexpired lease to `VALIDATION_IN_PROGRESS`; and a stale fencing token to `VALIDATION_SUPERSEDED`. Messages are fixed provider-specific variants and never include raw provider content.

Provider mapping:

- OpenAI: official `GET /v1/models`; invalid only when parsed JSON contains `error.code == "invalid_api_key"`. Message/status alone never marks invalid.
- Gemini: official `GET /v1beta/models?pageSize=1`; invalid only when `error.details` contains `@type == "type.googleapis.com/google.rpc.ErrorInfo"` and `reason` is `API_KEY_INVALID`, `API_KEY_EXPIRED`, `API_KEY_NOT_FOUND`, or credential-specific `INVALID_CREDENTIAL`.
- Unknown statuses/reasons, permission, quota, rate-limit, network, timeout, malformed, and service failures are temporary.

An unexpired validation lease returns `outcome: temporary`, `code: VALIDATION_IN_PROGRESS`, without a second provider call. A stale provider response returns temporary `VALIDATION_SUPERSEDED` with the latest safe snapshot and cannot update the key.

**Errors before validation is accepted**:

- `404 PROVIDER_KEY_NOT_FOUND` - same opaque rule as activation.
- `409 BRAND_CLEANUP_REQUIRED` - brand cleanup is pending; after owned key resolution this takes precedence over key cleanup.
- `409 KEY_CLEANUP_REQUIRED` - key cleanup is pending while the brand is active, including when a successful Vault query confirms the referenced secret is absent and atomically fences the key.
- `502 VAULT_UNAVAILABLE` - database/decryption access failed before a lease committed; persisted state is preserved.

## `DELETE /api/v1/brands/{brand_id}/keys/{key_id}`

Permanently delete one active, inactive, or cleanup-required key. No body. Deleting an active key never activates a replacement.

The operation first makes the row cleanup-required/inactive as a durable retry anchor. It then atomically removes the Vault secret and row. An already-absent Vault secret is success.

**Response `204`**: no body; both secret and row are absent.

**Errors**:

- `404 PROVIDER_KEY_NOT_FOUND` - same opaque rule as activation.
- `409 BRAND_CLEANUP_REQUIRED` - whole-brand cleanup owns the retry path; retry brand deletion instead.
- `503 KEY_CLEANUP_REQUIRED` - cleanup failed after the row was fenced. The row remains visible and inactive; retry the same DELETE.

After any network/5xx/unknown delete outcome, including a lost `204` or ambiguous commit, the client re-lists the owned brand's keys. Absence of the target ID confirms successful deletion; presence means the client surfaces its state and may explicitly retry. The server does not weaken opaque `404` semantics to distinguish this case.

## Existing Contract Change: `DELETE /api/v1/brands/{brand_id}`

Provider Keys strengthens the existing hard-delete behavior:

1. Verify owned brand and exact confirmation name.
2. Fence the brand as cleanup-required and fence all provider keys inactive/cleanup-required.
3. Repeatedly list and batch-delete every object under the brand's complete Storage prefix until a final listing confirms it empty. Missing objects are success; any list/delete/verification failure retains the fenced brand.
4. Atomically delete all Vault secrets and provider-key rows, verify none remain, and hard-delete the brand.

**Response `204`** only when the brand row, complete Storage prefix, provider-key/idempotency/asset-operation rows, and Vault secrets are absent.

**New error**:

- `503 BRAND_CLEANUP_REQUIRED` - Storage or Vault cleanup did not complete. The physical brand remains visible but mutation-fenced; retry the same confirmed DELETE. No successful-deletion response is emitted.

The existing `404 BRAND_NOT_FOUND` and `409 CONFIRMATION_MISMATCH` behavior remains unchanged.

After any network/5xx/unknown brand-delete outcome, the client re-lists owned brands; absence confirms completion, while a present cleanup-required brand retains explicit retry.

## Existing Brand/Logo Contract Changes

Every endpoint returning the shared Brand shape (create, list, detail, logo upload) adds `cleanup_state: "normal" | "cleanup_required"`. Cleanup-required brands remain visible with a retry-deletion action, while create-key, logo upload/remove, and other mutations are disabled.

Logo upload/removal creates a durable backend-only asset-operation record before Storage I/O. Requests against a hidden brand return `404 BRAND_NOT_FOUND`; requests against an owned cleanup-required brand return `409 BRAND_CLEANUP_REQUIRED`. A concurrent brand delete returns `409 BRAND_MUTATION_IN_PROGRESS` while any in-progress or cleanup-required asset operation exists and can be retried after that operation is reconciled.

Uploads write a unique operation-owned path `brands/{brand_id}/logos/{operation_id}.{ext}` and record the previous path. They update `logo_path` only while completing that operation on an active brand, then delete/verify the previous path before removing the operation row. Stale cleanup targets only its own recorded paths. Removal captures and deletes the current object first, then clears `logo_path` only while completing that operation. Definitive Storage failure preserves `logo_path`; ambiguous timeout/crash retains a cleanup-required operation with unknown remote status and returns a retryable Storage error.

Elapsed time and absence polling alone never clear an unknown operation. Startup/request-time reconciliation marks abandoned operations cleanup-required. If a definitive remote outcome cannot be established, operator recovery is required and brand deletion remains blocked; no successful hard-delete response is possible while a late Storage write could still occur.

Brand hard delete repeatedly paginates and batch-deletes the complete `brands/{brand_id}/` prefix, including legacy and tokenized objects, from offset zero until empty. It performs a final empty-prefix verification before database hard delete. Any list, batch-delete, or verification failure returns `BRAND_CLEANUP_REQUIRED` and retains the fenced brand.

## Shared Safe Error Codes

| Status | Code | Fixed safe message |
|---|---|---|
| 401 | `UNAUTHORIZED` | `Sign in required.` |
| 400 | `VALIDATION_ERROR` | Field-specific fixed validation message without submitted values |
| 404 | `BRAND_NOT_FOUND` | `Brand not found.` |
| 404 | `PROVIDER_KEY_NOT_FOUND` | `Provider key not found.` |
| 409 | `KEY_INVALID` | `Validate this key successfully before activating it.` |
| 409 | `KEY_CLEANUP_REQUIRED` | `Key cleanup is required. Retry deletion.` |
| 409 | `BRAND_CLEANUP_REQUIRED` | `Brand cleanup is required. Retry deletion.` |
| 409 | `BRAND_MUTATION_IN_PROGRESS` | `A brand update is in progress. Retry shortly.` |
| 409 | `IDEMPOTENCY_KEY_RETIRED` | `This add request was already completed and deleted. Use a new request ID.` |
| 502 | `VAULT_UNAVAILABLE` | `Secure key storage is unavailable right now.` |
| 503 | `KEY_CLEANUP_REQUIRED` | `Key cleanup did not complete. Retry deletion.` |
| 503 | `BRAND_CLEANUP_REQUIRED` | `Brand cleanup did not complete. Retry deletion.` |
| 500 | `INTERNAL_SERVER_ERROR` | `Unexpected error.` |

Messages never interpolate keys, labels, hints, Vault IDs, SQL text, provider bodies, or exception text. Clients do not automatically retry add/activate/validate; cleanup-required UI disables those controls and retains only explicit deletion retry.

## Logging Contract

Provider-key logs contain only fixed event names, request ID, provider, safe outcome code, duration, and optionally a provider request ID. They never contain:

- Raw keys, key hints, labels, Vault UUIDs, authorization headers, request bodies, or decrypted values.
- Raw OpenAI/Gemini response bodies or exception messages.
- Email addresses, user IDs, or other PII.

SQL bind values and outbound HTTP headers must not be emitted by engine/client debug logging.
