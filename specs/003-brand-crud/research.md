# Phase 0 Research: Brand CRUD

No `NEEDS CLARIFICATION` markers remain in the Technical Context — the one open
question this feature had (logo max file size) was already resolved in `spec.md` via
`/speckit-clarify`. The research below covers implementation-level decisions needed
to build against the existing codebase conventions, not open scope unknowns.

## Decision 1: RLS + base GRANTs in the same migration

**Decision**: `00014_create_brands.sql` creates the table, indexes, `updated_at`
trigger, `ENABLE`/`FORCE ROW LEVEL SECURITY`, the four owner-scoped RLS policies
(`brands_select`/`insert`/`update`/`delete`, exactly as specified in
`docs/implementation-plan.md`), **and** `GRANT SELECT, INSERT, UPDATE, DELETE ON
brands TO authenticated, service_role` — all in one migration, not split across two.

**Rationale**: `001-user-auth-profile` shipped `profiles` with RLS but no base
`GRANT`s, and it broke — even `service_role` (which bypasses RLS entirely) got
"permission denied for table profiles," because RLS narrows access that a `GRANT`
must first allow; RLS alone doesn't grant anything. That required a follow-up
migration (`00013_grant_profiles_privileges.sql`) discovered only when quickstart
validation actually ran against a real Supabase instance. This feature avoids
repeating that by including the `GRANT`s in the same migration as the table and RLS
policies from the start.

**Alternatives considered**:
- *Follow the same split pattern (table+RLS now, grants later if something breaks)*:
  Rejected — the fix is already known and cheap; there's no reason to reintroduce a
  bug that's already been diagnosed once in this exact codebase.

## Decision 2: Storage bucket provisioned via migration, not `config.toml`

**Decision**: `00015_create_brand_assets_bucket.sql` creates the `brand-assets`
bucket via `insert into storage.buckets (id, name, public) values ('brand-assets',
'brand-assets', true) on conflict (id) do update set public = excluded.public` —
idempotent, and self-healing if the bucket already exists with `public = false`
(e.g. manually changed via Studio) rather than silently leaving that drift in
place — instead of declaring it in `supabase/config.toml`.

**Rationale**: This repo manages all schema via versioned SQL migrations
(`supabase migration up`), applied identically to local and hosted Supabase. The
Storage schema (`storage.buckets`, `storage.objects`) is regular Postgres, reachable
from a migration the same way `auth.users` triggers already are (see
`00011_create_profile_signup_trigger.sql`). `config.toml`'s bucket declarations are
a local-CLI convenience feature for `supabase start` emulation; relying on it would
mean the bucket exists locally but not on a hosted project unless someone remembers
a separate manual step. A migration is the single source of truth for both.

**Alternatives considered**:
- *`config.toml` `[storage.buckets.brand-assets]`*: Rejected — doesn't provision the
  bucket on a hosted Supabase project, only local emulation; would need a duplicate
  manual step for hosted (the kind of gap `001-user-auth-profile`'s
  `T045 hosted Supabase manual config` task exists to track, better avoided than
  added to).
- *No dedicated Storage RLS policies on `storage.objects`*: all logo writes/deletes
  go through the backend using the service-role key (Decision 3), which bypasses
  Storage RLS the same way it bypasses Postgres RLS. Public read access comes from
  the bucket's own `public = true` flag, not from an RLS policy. No client ever
  writes to Storage directly in this feature, so no `authenticated`-role Storage
  policy is needed yet.

## Decision 3: Logo upload/delete is backend-mediated, not a client-side direct-to-Storage upload

**Decision**: The frontend sends the logo file as `multipart/form-data` to
`POST /api/v1/brands/{id}/logo`. The backend validates ownership, content-type, and
size (FR-006, FR-011) server-side, then uploads to Supabase Storage itself via
`httpx` using `SUPABASE_SECRET_KEY` (service-role), following the same
httpx-against-Supabase-REST-API pattern `routes/auth.py` already uses for the login
proxy. The frontend never receives a Storage upload token or talks to Storage
directly.

**Rationale**: The constitution's Security Rules require brand ID (and, by the same
logic, any write tied to it) to be verified server-side — "client assertions are
insufficient." A client-side direct-to-Storage upload (e.g., a signed URL) would mean
trusting the client to have already been authorized for the exact path being written
to, which is exactly the kind of client-side trust this project's security posture
rejects. Backend-mediated upload also gives one place to enforce the 5 MB/format
limit authoritatively (a client-side check alone is trivially bypassable).

**Old logo cleanup**: On a new upload, the backend looks up the brand's current
`logo_path` before uploading the replacement. Because the path includes the file
extension (`brands/{id}/logo.{ext}`), a same-format re-upload (e.g. PNG → PNG)
produces the *identical* path as the existing logo, while a format change (e.g.
PNG → JPEG) produces a different one — the cleanup step MUST NOT treat these two
cases the same way, or a same-format replacement would delete the logo that was
just uploaded:

1. Upload the new object to its computed path using Storage's upsert/overwrite
   behavior (so a same-path upload safely replaces the existing object's content
   at the storage layer itself, rather than the backend managing overwrite
   semantics manually).
2. Update `brands.logo_path` to the new path.
3. Only if the old path was set **and differs** from the new path (a format
   change), delete the old object — this is safe because it's a genuinely
   different key from the one just uploaded. If old and new paths are the same,
   skip this step entirely; the upsert in step 1 already replaced the content,
   and there is nothing else to clean up.

As before, if the step-3 cleanup delete fails, the backend logs it and still
reports success to the user (the new logo is live and correct) rather than
blocking on a non-critical storage cleanup — the same best-effort-cleanup
precedent already established in this spec's edge cases for brand deletion. This
ordering also means a failure between steps 1 and 2 can't destroy the old logo:
the old object is never touched until the new one is confirmed uploaded.

**Alternatives considered**:
- *Client uploads directly to Supabase Storage with a short-lived signed URL*:
  Rejected per the rationale above — moves authorization-relevant validation to a
  path the backend doesn't control as tightly, for no benefit at this scale (logo
  files are small; there's no throughput reason to bypass the backend).

## Decision 4: `is_brand_owner()` helper is deferred to Phase 4

**Decision**: This feature does **not** create the `is_brand_owner(p_brand_id UUID)`
SECURITY DEFINER function from `docs/implementation-plan.md`. The `brands` table's
own RLS policies check `owner_user_id = auth.uid()` directly — they don't need the
helper, which exists specifically for *other* tables (`brand_kits`, `provider_keys`,
`generations`) that only have a `brand_id` foreign key, not `owner_user_id` directly.

**Rationale**: None of those other tables exist yet. Creating an unused database
function now would be premature — Phase 4 (Provider Keys), the first phase that
actually needs it, is the natural place to introduce it alongside the first table
that calls it.

**Alternatives considered**:
- *Create it now since it's cheap and will be needed soon*: Rejected — keeps this
  migration scoped to only what it uses; avoids a dangling, untested DB object with
  no caller until a later phase.
