# Brand Kit API Contract

Base path: `/api/v1/brands`. Every operation requires `Authorization: Bearer <supabase_access_token>`.

## GET `/brands/{brand_id}/kit`

Returns the owner’s kit. If no row exists, return a valid empty kit with `status: "not_started"`, empty answers, null summary, and null `completed_at`.

### Complete response

```json
{
  "brand_id": "uuid",
  "brand_name": "My Brand",
  "answers": {
    "tagline": "Innovation for everyone",
    "tone": "professional",
    "audience": "Small business owners aged 25-45",
    "colors": ["#FF5733", "#3498DB"],
    "avoid_words": "cheap, discount"
  },
  "summary": "Brand: My Brand\nTagline: Innovation for everyone\n...",
  "status": "complete",
  "completed_at": "2026-07-29T00:00:00Z",
  "updated_at": "2026-07-29T00:00:00Z"
}
```

## PUT `/brands/{brand_id}/kit`

Upserts the existing brand name and kit answers. The client may send partial answers; status, summary, and completion time are derived by the server. For a partial request, omitted answer fields preserve their existing values, while explicit null or empty values clear the corresponding field.

```json
{
  "name": "My Brand",
  "answers": {
    "tagline": "Innovation for everyone",
    "tone": "professional",
    "audience": "Small business owners aged 25-45",
    "colors": ["#FF5733", "#3498DB"],
    "avoid_words": "cheap, discount"
  }
}
```

The response uses the same shape as GET. A partial save returns `in_progress` with `summary` and `completed_at` set to null; a valid complete save returns `complete` with summary and `completed_at`.

## Validation

- `name`: trimmed, 2–120 characters, updates the existing brand name.
- `tagline`: optional, at most 160 characters.
- `tone`: one of `formal`, `casual`, `playful`, `professional`, `friendly`.
- `audience`: optional while partial; 2–500 non-whitespace characters when supplied and required for completion.
- `colors`: zero values while partial, otherwise 1–3 valid hexadecimal colors for completion.
- `avoid_words`: optional.

## Errors

Use the project envelope `{ "error": { "code", "message", "request_id" } }`.

| Condition | Status | Code |
|---|---:|---|
| Missing/invalid session | 401 | `UNAUTHORIZED` |
| Brand absent or not owned by caller | 404 | `BRAND_NOT_FOUND` |
| Invalid request fields | 400 | `VALIDATION_ERROR` |
| Brand cleanup in progress | 409 | `BRAND_CLEANUP_REQUIRED` |

Unauthorized requests must not reveal whether another user’s brand or kit exists.
