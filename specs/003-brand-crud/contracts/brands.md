# Contract: Brand CRUD API

All endpoints require `Authorization: Bearer <supabase_access_token>` (verified per
`backend/app/auth.py`'s existing HS256/JWKS handling) and are scoped to the
authenticated user's own brands. Error responses use the existing shape:

```json
{ "error": { "code": "ERROR_CODE", "message": "Human readable message", "request_id": "uuid" } }
```

## `GET /api/v1/brands`

List the caller's brands, newest first.

**Response `200`**:
```json
{
  "brands": [
    {
      "id": "uuid",
      "name": "My Brand",
      "logo_url": "https://.../brand-assets/brands/{id}/logo.png",
      "created_at": "2026-07-25T00:00:00Z"
    }
  ]
}
```
`logo_url` is `null` when no logo has been uploaded. No pagination in this phase
(SC-003 targets up to 50 brands — a single unpaginated query is sufficient).

## `POST /api/v1/brands`

Create a brand (FR-001).

**Request**:
```json
{ "name": "My Brand" }
```

**Response `201`**: same shape as one list item, `logo_url: null`.

**Errors**:
- `400 VALIDATION_ERROR` — name missing, empty after trim, or outside 2–120 chars (FR-002).
- `409 BRAND_NAME_TAKEN` — case-insensitive duplicate of an existing brand owned by this user (FR-003).

## `GET /api/v1/brands/{id}`

Get one brand's details (FR-005).

**Response `200`**: same shape as a list item.

**Errors**:
- `404 BRAND_NOT_FOUND` — brand doesn't exist, or exists but isn't owned by the caller (FR-007 — identical response in both cases).

## `DELETE /api/v1/brands/{id}`

Hard delete a brand and its logo, if any (FR-012, FR-013, FR-014, FR-015).

**Request**:
```json
{ "confirm_name": "My Brand" }
```
`confirm_name` MUST exactly match the brand's current `name` (no trimming or
case-insensitivity — this is a deliberate confirmation gate, not the same
comparison FR-003 uses for duplicate detection). The frontend's type-the-name-to-
confirm control (FR-013) sends whatever the user typed verbatim; the backend is the
one that actually enforces the match, not just the UI — a request with a missing or
mismatched `confirm_name` MUST be rejected server-side, since any client holding a
valid bearer token could otherwise call this endpoint directly and skip the
confirmation step entirely.

**Response**: `204 No Content`.

**Errors**:
- `404 BRAND_NOT_FOUND` — same non-owner/nonexistent opacity as `GET`.
- `409 CONFIRMATION_MISMATCH` — `confirm_name` missing or doesn't exactly match the brand's current name. No deletion occurs.

Deletion order: validate `confirm_name` first (before touching Storage or the DB
row); delete the Storage object (if `logo_path` is set) before deleting the
`brands` row, then delete the row. If Storage deletion fails, the failure is logged
and the DB row deletion still proceeds — per `research.md` Decision 3's best-effort
cleanup precedent, a transient Storage error must not make a brand permanently
undeletable.

## `POST /api/v1/brands/{id}/logo`

Upload or replace a brand's logo (FR-008, FR-010).

**Request**: `multipart/form-data`, single file field.

**Response `200`**: same shape as a list item, with the new `logo_url`.

**Errors**:
- `404 BRAND_NOT_FOUND` — same opacity rule.
- `400 UNSUPPORTED_MEDIA_TYPE` — not PNG/JPEG/WebP (FR-011).
- `413 FILE_TOO_LARGE` — exceeds 5 MB (FR-011, per spec Clarifications).

## `DELETE /api/v1/brands/{id}/logo`

Remove a brand's logo (FR-009).

**Response**: `204 No Content`. Succeeds even if the brand currently has no logo
(idempotent — matches the edge case "what happens when removing a logo that doesn't
exist" resolution: no error, no-op success).

**Errors**:
- `404 BRAND_NOT_FOUND` — same opacity rule.
