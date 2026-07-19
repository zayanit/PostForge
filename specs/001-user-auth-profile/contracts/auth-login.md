# Contract: POST /api/v1/auth/login

New endpoint, not part of `docs/implementation-plan.md`'s original endpoint list — added
by this feature to satisfy FR-006a (see research.md § 1). Unauthenticated (this endpoint
establishes the session).

## Request

```json
{
  "email": "jane@example.com",
  "password": "correct horse battery staple"
}
```

## Responses

### 200 — Success

```json
{
  "access_token": "eyJ...",
  "refresh_token": "...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

Body mirrors Supabase Auth's password-grant token response, passed through unmodified.
On success, the backend resets `login_attempts` for this email (deletes the row or sets
`failed_count = 0, locked_until = NULL`).

### 400 — Invalid credentials or unregistered email (FR-006)

```json
{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "The email or password you entered is incorrect.",
    "request_id": "uuid"
  }
}
```

Returned identically whether the email is registered or not, and whether the password is
merely wrong or the account doesn't exist. On this outcome (and only this outcome), the
backend increments `login_attempts.failed_count` for the normalized email, setting
`locked_until` if the count reaches 5.

### 429 — Temporarily locked out (FR-006a)

```json
{
  "error": {
    "code": "ACCOUNT_TEMPORARILY_LOCKED",
    "message": "Too many failed attempts. Try again in a few minutes.",
    "request_id": "uuid"
  }
}
```

Returned when `login_attempts.locked_until` for this email is in the future. No call is
made to Supabase Auth in this case (the backend short-circuits before checking the
password), and `failed_count` is not incremented further while locked.

## Non-functional notes

- The backend MUST NOT log the request body (contains a plaintext password) or the
  response's `access_token`/`refresh_token`, per the constitution's Security Rules and
  the plan's Constraints.
- Email is normalized (trimmed, lowercased) before use as the `login_attempts` key so
  that case/whitespace variants of the same address share one lockout counter.
