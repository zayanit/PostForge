# Data Model: Image Generation

Source of truth: `supabase/migrations/00019_create_generations.sql`.

## `generations`

One row is one brand-scoped job and its result. It is also the idempotency receipt for its submission.

| Field | Type | Rules |
|---|---|---|
| `id` | uuid | Primary key |
| `brand_id` | uuid | Required; `REFERENCES brands(id) ON DELETE CASCADE` |
| `request_id` | uuid | Required; the client's `Idempotency-Key`; unique with `brand_id` |
| `request_hash` | text | SHA-256 of the normalized request; a different hash for the same key is a conflict |
| `prompt` | text | Required; 3–4,000 characters after trimming |
| `context_snapshot` | text | Required; brand name plus any Brand Kit answers at submission time |
| `provider` | `provider_t` | Default and only allowed value: `openai` |
| `model` | text | Default and only allowed value: `gpt-image-2` |
| `provider_key_id` | uuid | Opaque key reference at submission; `ON DELETE SET NULL` |
| `platform_preset` | text | One of the 13 preset IDs |
| `width`, `height` | integer | Preset dimensions; each 256–4,096 |
| `status` | text | `pending`, `processing`, `succeeded`, or `failed` |
| `lease_token` | uuid | Set only while `processing` |
| `lease_expires_at` | timestamptz | Set only while `processing` |
| `upload_fence_until` | timestamptz | Set before an upload; cleared on finish |
| `provider_request_id` | text | OpenAI `x-request-id` (max 200 characters), for support |
| `image_path` | text | `brands/{brand_id}/generations/{id}.png`, only when `succeeded` |
| `error_code` | text | Set only when `failed` |
| `cleanup_required` | boolean | Set while a deletion is in progress or has failed |
| `created_at` | timestamptz | Default `now()` |
| `completed_at` | timestamptz | Set when `succeeded` or `failed` |

### Constraints

- `UNIQUE (brand_id, request_id)`.
- `image_path` is either null or exactly the deterministic path above.
- `succeeded` requires `image_path` and `completed_at`, with no `error_code`. `failed` requires `error_code` and `completed_at`, with no `image_path`. `pending`/`processing` have neither.
- `processing` requires `lease_token` and `lease_expires_at`; other states have neither.

### Indexes

- `generations_history (brand_id, created_at DESC, id DESC)`: history pages.
- `generations_queue (created_at) WHERE status = 'pending'`.
- `generations_recovery (lease_expires_at) WHERE status = 'processing'`.

### Access

- RLS enabled and forced. `authenticated` may `SELECT` only rows of brands it owns (`private.is_brand_owner`); clients have no write privileges.
- The backend role (`DATABASE_URL`) needs SELECT/INSERT/UPDATE/DELETE. API and worker startup assert this.

## Lifecycle

```text
                submit (202)
                     │
                     ▼
               ┌──────────┐   delete (fence → remove → delete row)
               │ pending  │──────────────────────────────────────────► (gone)
               └────┬─────┘
           claim    │ (lease token, 5-minute lease, renewed every 15s)
                    ▼
               ┌────────────┐  lease expires → reclaimed with recovery=true:
               │ processing │  image already stored → succeeded
               └──┬──────┬──┘  otherwise           → failed (GENERATION_INTERRUPTED)
          upload  │      │ provider/key/image error
          + finish▼      ▼
         ┌───────────┐ ┌────────┐
         │ succeeded │ │ failed │
         └─────┬─────┘ └───┬────┘
               └─────┬─────┘
                     ▼  delete: cleanup_required=true → storage delete → row delete
                  (gone)   (a storage failure leaves cleanup_required=true for retry)
```

Processing rows cannot be deleted. Brand deletion fences the brand, so no lease can renew or publish, then removes the brand's generation prefix; the rows go with the brand through `ON DELETE CASCADE`.

### Error codes

`OPENAI_KEY_REQUIRED`, `OPENAI_KEY_REJECTED`, `PROVIDER_RATE_LIMITED`, `PROVIDER_REJECTED`, `PROVIDER_UNAVAILABLE`, `PROVIDER_TIMEOUT`, `INVALID_PROVIDER_IMAGE`, `GENERATION_INTERRUPTED`.

## Storage: `generation-assets` bucket

- Private, `image/png` only, 50 MB object limit.
- No client object policies; the backend signs URLs after an ownership check.
- Object path: `brands/{brand_id}/generations/{generation_id}.png`, written with `x-upsert: false`.
