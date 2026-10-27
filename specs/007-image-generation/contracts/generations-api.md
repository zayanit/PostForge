# Generations API Contract

Base path: `/api/v1/brands`. Every operation requires `Authorization: Bearer <supabase_access_token>`, verifies brand ownership server-side, and responds with `Cache-Control: private, no-store`. Errors use the standard envelope `{"error": {"code", "message", "request_id"}}`.

## GET `/generation-presets`

Returns the 13 presets in canonical order.

```json
{"presets": [{"id": "instagram_post", "width": 1080, "height": 1080, "label": "Instagram Post"}]}
```

## POST `/{brand_id}/generate` → 202

Headers: `Idempotency-Key: <uuid>` (required).

```json
{"prompt": "A bright garden product launch", "platform_preset": "instagram_post"}
```

Optional `provider` (`"openai"`) and `model` (`"gpt-image-2"`); any other field is rejected. The prompt is trimmed and must be 3–4,000 characters. The response is a [Generation](#generation-object) with `status: "pending"`. Repeating the key with identical input returns the existing generation in its current state.

| Status | Code | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Bad prompt, unknown preset, extra field, or missing/invalid `Idempotency-Key` |
| 404 | `GENERATION_NOT_FOUND` | Brand missing or not owned |
| 409 | `OPENAI_KEY_REQUIRED` | No active, usable OpenAI key for the brand |
| 409 | `IDEMPOTENCY_CONFLICT` | Key reused with different input |
| 409 | `BRAND_CLEANUP_REQUIRED` | Brand is being deleted |

## GET `/{brand_id}/generations` → 200

Query: `page` (≥1, default 1), `per_page` (1–100, default 20), `status` (`pending`/`processing`/`succeeded`/`failed`), `provider` (`openai`/`gemini`). Newest first.

```json
{"generations": [/* Generation */], "page": 1, "per_page": 20, "total": 1}
```

Errors: 404 `GENERATION_NOT_FOUND`; 503 `STORAGE_UNAVAILABLE` if a signed URL cannot be issued.

## GET `/{brand_id}/generations/{generation_id}` → 200

One [Generation](#generation-object), with a freshly signed `image_url` when it succeeded. Errors: 404 `GENERATION_NOT_FOUND`; 503 `STORAGE_UNAVAILABLE`.

## DELETE `/{brand_id}/generations/{generation_id}` → 204

Physically removes the PNG (if any) and the row.

| Status | Code | When |
|---|---|---|
| 404 | `GENERATION_NOT_FOUND` | Brand or generation missing or not owned |
| 409 | `GENERATION_PROCESSING` | The job is being processed |
| 409 | `GENERATION_ASSET_BUSY` | Another publication or deletion for this brand holds the asset lock; retry shortly |
| 503 | `STORAGE_UNAVAILABLE` | Storage deletion failed; the row stays with `cleanup_required: true` |

## Generation object

```json
{
  "id": "uuid",
  "brand_id": "uuid",
  "prompt": "A bright garden product launch",
  "provider": "openai",
  "model": "gpt-image-2",
  "platform_preset": "instagram_post",
  "width": 1080,
  "height": 1080,
  "status": "succeeded",
  "error_code": null,
  "image_url": "https://<project>.supabase.co/storage/v1/object/sign/generation-assets/...?token=...",
  "image_url_expires_at": "2026-10-27T12:05:00Z",
  "cleanup_required": false,
  "created_at": "2026-10-27T12:00:00Z",
  "completed_at": "2026-10-27T12:00:42Z"
}
```

`image_url` is present only for succeeded generations that are not being deleted. It is a bearer link valid for five minutes; it must not be logged or stored. Responses never include `context_snapshot`, `provider_key_id`, lease fields, `request_hash`, or `image_path`.

## Related change: brand deletion

`DELETE /api/v1/brands/{brand_id}` now also removes the brand's generated images. It returns 409 `BRAND_MUTATION_IN_PROGRESS` without marking the brand for deletion when a generation is being saved or deleted at that moment. It returns 503 `BRAND_CLEANUP_REQUIRED` (brand stays fenced, retry later) while an upload's outcome is uncertain.
