# Implementation Plan: Provider Keys

**Branch**: `004-provider-keys` | **Date**: 2026-07-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-provider-keys/spec.md`

## Summary

Deliver brand-scoped OpenAI and Gemini BYOK management: add/list safe key metadata, atomically select one active key per provider, validate through official read-only provider endpoints, and hard-delete both Vault secrets and application records. Raw keys are created, decrypted, and removed through Supabase Vault on the existing PostgreSQL connection, allowing Vault and metadata writes to share real transactions; add requests use persisted idempotency UUIDs for ambiguous commits. Provider HTTP validation uses the existing `httpx` dependency with a persisted lease/fencing token and a 15-second absolute deadline. Cleanup failures retain inactive, owner-visible retry anchors; brand deletion is upgraded to fence key and tokenized logo mutations and report success only after the complete Storage prefix, Vault secrets, key records, and brand row are physically gone.

## Technical Context

**Language/Version**: Python 3.11 (FastAPI backend); TypeScript 5.x (Next.js 15 App Router frontend); PostgreSQL SQL migrations

**Primary Dependencies**: Existing FastAPI, Pydantic v2, SQLAlchemy raw `text()` queries, `httpx`, Supabase Auth/Postgres/Vault, React 18; no provider SDK or new runtime dependency

**Storage**: Supabase PostgreSQL (`provider_keys`, brand deletion lifecycle, RLS) and Supabase Vault (`vault.secrets`/`vault.decrypted_secrets`, opaque UUID references only)

**Testing**: pytest contract/unit/integration tests, `httpx.MockTransport` for deterministic provider classifications, real local Supabase for Vault/RLS/concurrency/hard-delete tests; frontend ESLint, TypeScript, production build, and focused Playwright flow where practical

**Target Platform**: Existing single Bunny Magic Linux container; FastAPI internal port and Next.js public port unchanged; outbound HTTPS only to official OpenAI and Gemini hosts

**Project Type**: Existing three-part web monorepo (`frontend/`, `backend/`, `supabase/`) with runtime integration

**Performance Goals**: Add/list/activate/delete feel immediate at MVP key counts; provider validation always returns a classified result within 15 seconds, with at most 10 seconds spent on provider I/O

**Constraints**: Raw keys only in Supabase Vault and request-local memory; never client-visible/logged; SQL bind values hidden; server-side brand ownership on every operation; `ENABLE`/`FORCE RLS`; authenticated safe-column reads only and no direct writes; official provider endpoints only; no generation during validation; one active key per brand/provider under concurrency; no locks/connections held across provider or Storage awaits; external Storage mutations retain durable non-expiring operation records until reconciled; hard delete is physical and retryable, never soft delete

**Scale/Scope**: Two providers, normally one active plus a few historical keys per provider per brand; unpaginated key list; no automatic rotation/revalidation, key reveal/edit, provider account management, image generation, or background cleanup worker

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Applicability and design evidence | Status |
|---|---|---|
| I. Product Truth | Directly implements brand-scoped BYOK. Every key has exactly one brand and one owner through that brand. No sharing or billing introduced. | Pass |
| II. Non-Negotiables | Brand isolation is enforced server-side and by RLS. Key secrecy is enforced by Vault-only raw storage, safe response models, explicit logging restrictions, and denied client Vault access. Validation uses official OpenAI/Gemini endpoints only. Hard deletion removes Vault and DB records; generation/PNG rules are untouched. | Pass |
| III. Tech Constraints | Uses Constitution v2.0.0's fixed Next.js 15/FastAPI/Supabase/Bunny stack and adds no runtime dependency. | Pass |
| IV. Data Rules | Raw provider keys live only in Supabase Vault; `provider_keys` stores an opaque Vault UUID and safe metadata. | Pass |
| V. UX Rules | Generation, brand-kit interview, presets, and history UX are outside this feature; no conflicting UX is introduced. | Pass (N/A) |
| VI. Security Rules | `provider_keys` uses owner RLS and server-side ownership checks. Provider calls are backend-only. Logs are fixed safe metadata and exclude keys, tokens, PII, labels, hints, Vault IDs, and raw provider errors. | Pass |
| VII. Definition of Done | Universal acceptance, RLS/Vault isolation, logging/secrecy, and DB/Vault/Storage hard-delete checks are designed. OpenAI and Gemini checks apply because this feature introduces both integrations. Brand-kit scenarios are N/A under Constitution v2.0.0 because Brand Kit is not implemented and provider-key behavior does not consume it. | Pass (phase-aware) |

No gate violations require justification.

### Post-Design Re-check

Phase 1 adds `provider_keys`, a safe backend-only idempotency-receipt table, and a backend-only durable brand-asset-operation table, plus three narrow enums, one ownership helper, and deletion state on `brands`. All new tables have RLS/forced RLS; provider-key direct access is safe-column owner read only and all writes remain backend-only. Direct authenticated brand deletion is revoked and FK cascades that could bypass Vault/Storage cleanup become restrictive. Vault remains outside exposed schemas with exact client privilege revocation. Contracts contain no raw-key response field or Vault UUID. Provider validation is server-only against fixed official hosts and deterministic structured predicates. Cleanup-required state represents a failed operation and always leads to physical deletion on success; no completed soft-delete state exists. All applicable Constitution v2.0.0 gates pass after design.

## Project Structure

### Documentation (this feature)

```text
specs/004-provider-keys/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── provider-keys.md
└── tasks.md                         # Created later by /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── .env.example                     # Document private BYPASSRLS/Vault-capable DB role
├── app/
│   ├── auth.py                      # Apply remaining validation deadline to JWKS lookup
│   ├── config.py                    # Hide SQL bind parameters; backend-role privilege checks/timeouts
│   ├── main.py                      # Pre-auth validation deadline, router, safe log allowlist
│   ├── models/
│   │   ├── brand.py                 # Expose safe cleanup state
│   │   └── provider_key.py          # Add/list/validate response models; raw key request only
│   ├── routes/
│   │   ├── brands.py                # Extend confirmed brand hard-delete orchestration
│   │   └── provider_keys.py         # List/add/activate/validate/delete endpoints
│   └── services/
│       ├── brand_deletion.py        # Retryable Storage + Vault + row hard-delete coordinator
│       ├── brand_storage.py         # Token-owned logo mutation + exhaustive prefix cleanup
│       ├── brand_store.py           # Deletion/asset-operation fences for brand mutations
│       ├── provider_key_store.py     # SQL/Vault transactions, locking, lifecycle, leases
│       └── provider_validation.py    # Official OpenAI/Gemini httpx probes and safe mapping
└── tests/
    ├── contract/
    │   └── test_provider_keys.py     # API shapes, opacity, no raw values
    ├── unit/
    │   └── test_provider_validation.py # Provider mappings/deadlines with mock transport
    └── integration/
        ├── test_provider_keys.py     # Real Vault add/list/activate/delete/retry
        ├── test_provider_key_rls.py  # Metadata RLS; idempotency/asset-table and Vault denial
        └── test_provider_key_cleanup.py # Concurrency/failure injection + brand hard delete

frontend/
└── app/(dashboard)/brands/[brandId]/
    ├── page.tsx                     # Cleanup state, mutation fences, keys navigation/retry
    └── keys/page.tsx                # Provider tabs, add form, cards, status/actions

supabase/
└── migrations/
    └── 00016_create_provider_keys.sql # Vault prerequisite, enums/helper, restrictive FKs,
                                       # brand lifecycle, provider keys, idempotency and
                                       # asset-operation tables, constraints/RLS/grants/revokes

docs/
└── docker.md                         # Hosted DATABASE_URL role/Vault privilege requirement
```

**Structure Decision**: Continue the established routes → services → Pydantic model backend pattern and direct client-page fetch pattern. Vault transaction logic belongs in `provider_key_store.py` because Vault is accessed through the same SQL transaction as provider-key rows; a separate generic Vault abstraction would add indirection with no second caller. Provider HTTP classification is isolated because it is asynchronous, security-sensitive, and independently unit-testable. Brand deletion becomes a dedicated coordinator because it now spans existing Storage cleanup plus provider-key/Vault cleanup and is no longer a single store call.

## Complexity Tracking

No entries. The lifecycle/operation records are required by explicit hard-delete and key-secrecy rules, not constitutional exceptions.
