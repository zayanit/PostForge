# Implementation Plan: Brand Kit Interview

**Branch**: `006-brand-kit` | **Date**: 2026-07-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/006-brand-kit/spec.md`, grounded in `docs/implementation-plan.md` Phase 5.

## Summary

Implement the six-step Brand Kit interview across the FastAPI API, Supabase schema, and Next.js dashboard. Each brand has at most one owner-scoped `brand_kits` record; a brand with zero persisted answers has no kit row and is reported as `not_started`. Derive status and summary server-side, expose authenticated GET/PUT endpoints, and add a wizard route with auto-save, explicit save, resume, completion summary, and navigation status. Existing brand ownership, error formatting, and hard-delete behavior will be reused.

## Technical Context

**Language/Version**: Python 3.13, TypeScript/React 18, Next.js 15

**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy text queries, Supabase PostgreSQL/RLS, Supabase SSR client, Playwright

**Storage**: Supabase PostgreSQL `brand_kits` table with at most one row per brand; `brands` queries derive `kit_status` with a left join, defaulting a missing zero-answer row to `not_started`

**Testing**: Backend contract and unit tests, real Supabase integration/RLS tests, frontend Playwright E2E, ESLint, TypeScript/Next.js production build

**Target Platform**: FastAPI service and Next.js browser dashboard

**Project Type**: Full-stack web application

**Performance Goals**: Owner-scoped kit GET/PUT requests should complete within 500ms p95 under normal local/application load, excluding token verification and database startup.

**Constraints**: Use the existing `/api/v1` route convention and safe error envelope; never trust client ownership; enforce RLS and forced RLS; keep last-successful-save-wins semantics; do not call external AI providers for summary derivation.

**Scale/Scope**: One kit per brand, six fixed questions, at most three colors per kit, one new migration, two API operations, one wizard route, and a brand navigation status indicator.

## Constitution Check

*GATE: Pass before research and re-check after design.*

### Pre-design gate

- Product Truth: PASS — Brand Kit is the planned Phase 5 capability supporting future image generation and remains brand-scoped.
- Brand Isolation: PASS — every kit is keyed by `brand_id`; backend ownership checks and database RLS will be tested.
- Data Rules: PASS — answers and derived summary are persisted; no provider secrets or generated assets are involved.
- Security: PASS — authenticated access, server-side ownership checks, forced RLS, and generic 404 responses are required.
- Hard Delete: PASS — the kit row is removed by the existing brand deletion cascade; integration coverage will verify it.
- Universal DoD: applicable acceptance, RLS/privilege, ownership, and deletion checks are assigned to tests.
- Brand-kit capability checks: REQUIRED — this feature implements the zero-answer and complete-kit scenarios.
- Provider, generation lifecycle, and PNG checks: N/A — this feature does not call providers or create generations.

### Post-design gate

- PASS — design adds one RLS-protected table with owner policy, includes the table in backend privilege assertions, keeps ownership in the service transaction, and covers zero-answer, partial, complete, invalid, cross-user, and hard-delete paths.
- N/A remains justified for provider and generation checks because no provider or generation behavior is changed.

## Project Structure

```text
supabase/migrations/00017_create_brand_kits.sql

backend/app/models/brand_kit.py
backend/app/services/brand_kit_store.py
backend/app/routes/brand_kits.py
backend/app/config.py                         # privilege assertion update
backend/app/main.py                           # router registration
backend/app/models/brand.py                    # kit_status in brand responses
backend/app/services/brand_store.py            # derived status in brand queries
backend/tests/contract/test_brand_kits.py
backend/tests/unit/test_brand_kit_store.py
backend/tests/integration/test_brand_kit_rls.py
backend/tests/integration/test_brand_kits.py

frontend/app/(dashboard)/brands/page.tsx
frontend/app/(dashboard)/brands/[brandId]/kit/page.tsx
frontend/app/(dashboard)/brands/[brandId]/page.tsx
frontend/app/(dashboard)/layout.tsx
frontend/tests/e2e/brand-kit.spec.ts

specs/006-brand-kit/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── contracts/brand-kit.md
└── quickstart.md
```

**Structure Decision**: Follow the existing route/model/store separation in the backend and colocate the wizard under the existing brand dashboard route. Use the existing brand detail and dashboard layout as navigation integration points.

## Complexity Tracking

No constitution violations or additional projects are introduced.
