# Phase 1 Data Model: Brand CRUD

## Entity: Brand

Maps to the `brands` table, per `docs/implementation-plan.md`'s schema, provisioned
by `supabase/migrations/00014_create_brands.sql`.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | `gen_random_uuid()` default |
| `owner_user_id` | UUID (FK → `auth.users.id`, `ON DELETE CASCADE`) | Set once at creation from the authenticated user; never client-supplied |
| `name` | TEXT | `CHECK (char_length(btrim(name)) BETWEEN 2 AND 120)` — FR-002 |
| `logo_path` | TEXT, nullable | `CHECK (logo_path IS NULL OR logo_path ~ '^brands/[0-9a-f-]+/logo\.[A-Za-z0-9]+$')`; `NULL` when no logo uploaded |
| `created_at` | TIMESTAMPTZ | `DEFAULT now()` |
| `updated_at` | TIMESTAMPTZ | `DEFAULT now()`, maintained by `trg_brands_updated_at` (`BEFORE UPDATE`, `set_updated_at()` — same trigger function `profiles` already uses) |

### Uniqueness (FR-003)

```sql
CREATE UNIQUE INDEX uq_brands_owner_name_ci
  ON brands(owner_user_id, lower(name));
```

Enforced at the database layer, not just application validation — closes the race
where two concurrent create requests for the same name could otherwise both pass an
application-level pre-check. A violation surfaces as a Postgres unique-violation,
which the backend maps to the FR-003/edge-case duplicate-name error response.

### Lookup index

```sql
CREATE INDEX idx_brands_owner_created
  ON brands(owner_user_id, created_at DESC);
```

Supports the brand list query (SC-003: find any of up to 50 brands quickly) —
already scoped by `owner_user_id`, sorted newest-first.

### Row Level Security

```sql
ALTER TABLE brands ENABLE ROW LEVEL SECURITY;
ALTER TABLE brands FORCE ROW LEVEL SECURITY;

CREATE POLICY brands_select ON brands FOR SELECT
  USING (owner_user_id = auth.uid());

CREATE POLICY brands_insert ON brands FOR INSERT
  WITH CHECK (owner_user_id = auth.uid());

CREATE POLICY brands_update ON brands FOR UPDATE
  USING (owner_user_id = auth.uid())
  WITH CHECK (owner_user_id = auth.uid());

CREATE POLICY brands_delete ON brands FOR DELETE
  USING (owner_user_id = auth.uid());

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE brands TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE brands TO service_role;
```

The `GRANT`s are included in the same migration as the policies — see `research.md`
Decision 1 for why this matters (RLS narrows access a `GRANT` must first allow;
omitting the `GRANT` breaks access entirely, including for `service_role`).

FR-006/FR-007 (never reveal a non-owned brand's existence) are enforced at the API
layer on top of this: the backend's ownership-scoped lookup naturally returns "not
found" for both a nonexistent ID and one owned by someone else, since RLS makes the
row invisible to the requester either way when queried as the authenticated user;
the backend additionally applies the same "not found" response when using the
service-role connection, so behavior doesn't depend on which DB role executes the
query.

### Update column (`UPDATE`)

This feature does not expose a rename/edit endpoint (per spec — no FR requires
renaming). The `brands_update` policy and `UPDATE` grant exist because `logo_path`
changes are implemented as an `UPDATE` on the `brands` row (see Storage Asset below),
not because brand names are editable in this phase.

## Storage Asset: Brand logo

Not a database entity — an object in the `brand-assets` Supabase Storage bucket,
referenced by `brands.logo_path`.

- **Bucket**: `brand-assets`, `public = true` (provisioned by
  `00015_create_brand_assets_bucket.sql`)
- **Path**: `brands/{brandId}/logo.{ext}` where `{ext}` reflects the uploaded file's
  type (`png`, `jpg`/`jpeg`, or `webp`)
- **Constraints**: ≤ 5 MB, content-type restricted to PNG/JPEG/WebP (FR-011,
  validated server-side before upload — see `research.md` Decision 3)
- **Lifecycle**: created/replaced by `POST /brands/{id}/logo`, removed by
  `DELETE /brands/{id}/logo` or as a side effect of `DELETE /brands/{id}`
  (FR-014); at most one live object per brand at a time (FR-010) — a replacement
  upload deletes the previous object once the new one is confirmed stored
