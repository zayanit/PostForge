# Contract: GET / PATCH /api/v1/me

Already defined in `docs/implementation-plan.md` § API Endpoints › Account/Profile;
reproduced here as the contract this feature implements against, with validation rules
made explicit (FR-009, FR-010, FR-011).

Both endpoints require a valid Supabase JWT (`Authorization: Bearer <access_token>`).
The authenticated user's `auth.uid()` is the only identity ever operated on — there is no
request parameter for "which user," which is what makes FR-011 structurally true rather
than dependent on an application-level check.

## GET /api/v1/me

### 200 — Success

```json
{
  "user_id": "uuid",
  "email": "jane@example.com",
  "full_name": "Jane Doe",
  "avatar_url": "https://example.com/avatar.png",
  "created_at": "2026-07-19T00:00:00Z",
  "updated_at": "2026-07-19T00:00:00Z"
}
```

`email` is read from the Supabase Auth session, not the `profiles` table. `full_name` and
`avatar_url` are `null` if never set (FR-004: the profile row exists from signup, but its
fields start empty).

### 401 — No valid session

```json
{
  "error": { "code": "UNAUTHORIZED", "message": "Sign in required.", "request_id": "uuid" }
}
```

## PATCH /api/v1/me

### Request

```json
{
  "full_name": "Jane Doe",
  "avatar_url": "https://example.com/avatar.png"
}
```

Both fields optional; only fields present in the body are updated (partial update).

### 200 — Success

Returns the updated profile, same shape as `GET /api/v1/me`.

### 400 — Validation failure (FR-010)

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "full_name must be between 2 and 120 characters.",
    "request_id": "uuid"
  }
}
```

Returned when a field fails the `profiles` table's constraints (see data-model.md). The
previous values are left unchanged — no partial write occurs on validation failure.

### 401 — No valid session

Same shape as `GET /api/v1/me`'s 401.
