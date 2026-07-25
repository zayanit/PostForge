# Implementation Plan: Brand CRUD

**Branch**: `003-brand-crud` | **Date**: 2026-07-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-brand-crud/spec.md`

## Summary

Deliver brand creation, listing, detail view, logo upload/removal, and hard delete —
the foundational tenancy container every later phase (brand kit, provider keys,
generation) attaches to. Backend adds a `brands` table (owner-scoped, RLS + base
GRANTs from the start this time — see Decision in research.md about the gap that bit
`profiles` in 001-user-auth-profile) and a `brand-assets` Storage bucket, both
provisioned via a numbered migration matching this repo's existing convention. All
writes (including logo upload/delete to Storage) are backend-mediated using the
service-role key, consistent with the constitution's "brand ID MUST be verified
server-side" rule — the frontend never talks to Supabase Storage directly for this
feature. Frontend adds a brand list, create-brand page, and a combined brand
detail/settings page (logo + delete), plus a brand selector in the dashboard nav.

## Technical Context

**Language/Version**: Python 3.11 (FastAPI backend, matching existing `backend/app/`);
TypeScript 5.x (Next.js 15, App Router, matching existing `frontend/app/`)

**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy (raw `text()` queries via
the shared `get_engine()`, matching `profile_store.py`'s existing pattern — no ORM
models introduced); `httpx` for backend-to-Supabase-Storage calls (matching
`routes/auth.py`'s existing httpx-against-Supabase pattern rather than adding the
`supabase-py` SDK as a new dependency)

**Storage**: Supabase PostgreSQL — new `brands` table (this feature); Supabase
Storage — new `brand-assets` bucket (public, this feature) for logo images

**Testing**: pytest + httpx (backend contract/integration tests against a local
Supabase instance, matching `001-user-auth-profile`'s test structure); no new
frontend e2e tests required for MVP scope beyond what's already established
(Playwright is available in `frontend/tests/e2e/` if added later)

**Target Platform**: Web — single Bunny Magic container per `docs/implementation-plan.md`
(unchanged by this feature; brands API is added under the same FastAPI app, same
internal-only port)

**Performance Goals**: SC-001 (create → visible in list, under 1 minute — dominated by
human interaction, not backend throughput); SC-003 (find/open any of up to 50 brands
in under 10 seconds — a plain indexed list query, no pagination needed at this scale)

**Constraints**: Backend must verify brand ownership server-side for every operation
(FR-006); non-owner and non-existent brand IDs must be indistinguishable (FR-007,
same "don't leak existence" posture already established for login in
001-user-auth-profile); logo uploads capped at 5 MB and restricted to
PNG/JPEG/WebP (FR-011, per spec clarification); a brand name is unique per owner,
case-insensitive (FR-003, enforced at the DB layer via a unique index, not just
application-level validation, to close races)

**Scale/Scope**: MVP — this feature covers brand create/list/get/delete and logo
upload/delete only; brand kit, provider keys, and generations are out of scope (see
spec Assumptions) and their own phases will extend the `brands` table's cascade
behavior when they add tables that reference it

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applicability to this feature | Status |
|---|---|---|
| I. Product Truth (brand-based tenancy, BYOK, image generation) | Directly applicable — this feature *is* the brand-based tenancy container the rest of the product attaches to; no BYOK/generation concepts touched yet | Pass |
| II. Non-Negotiables (brand isolation, hard delete, key secrecy, official endpoints, PNG-only) | Hard Delete applies directly (FR-014: brand deletion removes both the DB row and the logo asset). Brand Isolation, Key Secrecy, Official Endpoints, PNG-only are N/A — no dependent resources, provider keys, or generated images exist yet | Pass |
| III. Tech Constraints (Next.js 14/15, FastAPI, Supabase, Bunny Magic) | Applicable — built entirely on the existing fixed stack, no deviation | Pass |
| IV. Data Rules (generation/brand-kit/provider-key storage rules) | Not applicable — this feature adds the `brands` table only; none of the Data Rules govern brand records themselves | Pass (N/A) |
| V. UX Rules (prompt-first, brand-kit interview, presets, history) | Not applicable — no generation UX in this feature | Pass (N/A) |
| VI. Security Rules (RLS on all tables; server-side verification; no secrets/PII in logs) | Applicable — `brands` table MUST have RLS enabled (+ base GRANTs, learned from the 001-user-auth-profile gap); ownership MUST be verified server-side for every brand/logo operation | Pass, enforced in design (see data-model.md) |
| VII. Definition of Done (brand-kit/provider/hard-delete checks) | Hard-delete-verified and RLS-tested items apply to `brands`; brand-kit-answers, OpenAI/Gemini-provider items are N/A — no brand kit or provider integration exists yet | Pass (feature-scoped subset: hard delete + RLS tested) |

No violations requiring justification — the N/A principles are non-applicable because
their subject matter (brand kit, provider keys, generations) doesn't exist in the data
model until later phases, not because a rule was bypassed. No Complexity Tracking
entries needed.

**Post-Phase 1 re-check**: Design adds one table (`brands`) and one Storage bucket
(`brand-assets`). RLS is enabled and forced on `brands` with owner-scoped policies,
and base `GRANT`s are included in the same migration (not left for a follow-up patch).
No secrets are involved in this feature (logos are non-sensitive public assets). No
new violations introduced.

## Project Structure

### Documentation (this feature)

```text
specs/003-brand-crud/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── brands.md
└── tasks.md              # Phase 2 output
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── models/
│   │   └── brand.py                 # New: Brand, BrandCreate, BrandResponse
│   ├── routes/
│   │   └── brands.py                # New: list/create/get/delete + logo upload/delete
│   └── services/
│       ├── brand_store.py           # New: DB access (list/create/get/delete), same
│       │                            #      raw-text()-via-get_engine() pattern as
│       │                            #      profile_store.py — no ORM introduced
│       └── brand_storage.py         # New: Supabase Storage upload/delete via httpx,
│                                     #      matching routes/auth.py's existing
│                                     #      httpx-against-Supabase pattern
└── tests/
    ├── contract/
    │   └── test_brands.py           # New: request/response shape per contracts/brands.md
    └── integration/
        ├── test_brand_crud.py       # New: create/list/get/delete against real Supabase
        └── test_brand_rls.py        # New: cross-user isolation, matching
                                      #      test_profile_rls.py's pattern

frontend/
├── app/
│   └── (dashboard)/
│       └── brands/
│           ├── page.tsx             # New: brand list
│           ├── new/page.tsx         # New: create-brand form
│           └── [brandId]/page.tsx   # New: brand detail + logo + delete (combined —
│                                     #      see Structure Decision)
└── app/(dashboard)/layout.tsx       # Modified: add brand selector to nav

supabase/
└── migrations/
    ├── 00014_create_brands.sql            # New: table + indexes + trigger + RLS +
    │                                      #      base GRANTs in one migration (see
    │                                      #      research.md — this is the fix for
    │                                      #      the gap 00013 had to patch after the
    │                                      #      fact in 001-user-auth-profile)
    └── 00015_create_brand_assets_bucket.sql  # New: public Storage bucket
```

**Structure Decision**: Continues the existing root-level `backend/`/`frontend/`
layout (no new top-level directories). Two deliberate deviations from
`docs/implementation-plan.md`'s illustrative structure, both to keep this phase's
diff minimal and consistent with what's actually in the codebase today:

1. **No `lib/api.ts` API client wrapper.** The existing `account/page.tsx` calls
   `fetch()` directly against `${NEXT_PUBLIC_API_URL}/v1/...` with a bearer token
   pulled from the Supabase session. Brand pages follow that same established
   pattern rather than introducing a new abstraction this feature doesn't need.
2. **Combined brand detail + settings + logo page**, not the separate
   `[brandId]/page.tsx` (generator) / `settings/page.tsx` / `kit/`, `keys/`,
   `history/` split shown in the implementation plan's full future tree. Those
   sibling routes belong to later phases (generation, keys, brand kit, history)
   that don't exist yet; splitting brand detail from brand settings today would
   just be two mostly-empty pages. `[brandId]/page.tsx` covers view + logo
   upload/remove + delete for this phase; later phases add their own sibling
   routes under `[brandId]/` without touching this one's responsibilities.

No modal-based create flow (`docs/implementation-plan.md`'s task list mentions a
"create brand modal," but its own frontend structure tree shows `brands/new/page.tsx`
— resolved in favor of a dedicated page, matching how every other form in this
codebase — signup, login, forgot-password — is a full page, not a modal).

## Complexity Tracking

*No entries — no Constitution Check violations.*
