# Implementation Plan: Image Generation (OpenAI-first release)

**Branch**: `007-image-generation` | **Date**: 2026-10-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/007-image-generation/spec.md`, grounded in `docs/implementation-plan.md` Phases 6 and 7.

> Written retroactively to record the design as built in commit `64d2a48` and
> revised in PR #24. See the process note in `spec.md`.

## Summary

Add OpenAI image generation as a durable, PostgreSQL-backed job queue. The API validates and persists a job (202) with a snapshot of brand context. A separate worker process, supervised inside the existing single container, claims jobs with leases, calls OpenAI, center-crops to the exact preset size, and uploads a PNG to a private Supabase Storage bucket. The UI polls job state, shows brand-scoped history with signed preview and download links, and supports permanent deletion. Brand deletion is extended to remove generated images.

## Technical Context

**Language/Version**: Python 3.11+ (tests run on 3.13), TypeScript/React, Next.js 15

**Primary Dependencies**: FastAPI, Pydantic v2, SQLAlchemy 2.0 text queries (psycopg2), httpx, Pillow 13, Supabase PostgreSQL/RLS/Vault/Storage, Playwright; `embedded-postgres` for isolated queue tests

**Storage**: `public.generations` (job, status, and result metadata) and a private `generation-assets` bucket (PNG objects at deterministic paths)

**Testing**: Backend unit and contract tests; integration tests against a disposable PostgreSQL that applies the real `00019` migration; a self-contained Playwright suite with mocked API and auth; release gates against real Supabase, Docker, and OpenAI

**Target Platform**: The existing single Linux container (Next.js, uvicorn, and now the worker under one entrypoint)

**Project Type**: Full-stack web application

**Performance Goals**: Submission and history requests return without waiting on the provider. Provider calls are bounded at 180 seconds. History polling avoids re-listing and re-signing while jobs are in progress.

**Constraints**: BYOK only; official OpenAI endpoint; PNG only; no automatic paid retries; forced RLS with client writes denied; no secrets, prompts, or signed URLs in logs; container health independent of Supabase.

**Scale/Scope**: 13 presets, one provider/model, one worker per container processing one job at a time, one migration, five API operations, two new pages.

## Constitution Check

*GATE: Pass before research and re-check after design.* (Evaluated retroactively against constitution v2.0.0.)

### Pre-design gate

- Product Truth: PASS — implements the product's sole capability, image generation.
- Brand Isolation: PASS — every generation belongs to one brand; ownership is verified server-side on every read and write and enforced by forced RLS.
- Hard Delete: PASS — deletion removes the stored PNG and the row; brand deletion removes the brand's generation prefix.
- Official Endpoints Only: PASS — `https://api.openai.com/v1/images/generations`, redirects disabled, environment proxies ignored (`trust_env=False`).
- PNG Output Only: PASS — every result is re-encoded as PNG.
- Data Rules: PASS — rows store prompt, provider, model, preset, dimensions, and storage path; keys are referenced by opaque ID and read from Vault only in the worker.
- UX Rules: PARTIAL — free-form prompt and mandatory preset (no default) are met. History is brand-scoped and filterable by status; the API accepts a provider filter but the UI does not expose one because only one provider exists (see Complexity Tracking).
- Security: PASS — provider calls are server-only; logs use an allowlist formatter.
- Universal DoD: assigned to tests — RLS/privileges/client denial, ownership, secret/logging rules, and physical deletion.
- Brand-kit checks: REQUIRED — generation reads Brand Kit; empty, partial, and complete snapshots are tested.
- OpenAI checks: REQUIRED — first OpenAI integration; deterministic provider tests plus a live release gate.
- Gemini checks: N/A — this feature does not integrate Gemini generation; existing Gemini key management is unchanged.
- Generation lifecycle, preset, and PNG checks: REQUIRED — covered by unit, integration, and browser tests.

### Post-design gate

- PASS with the UX exception above. The design adds one backend-written table with owner-read RLS, adds it to backend privilege assertions, serializes publication and deletion per brand, and covers lifecycle, recovery, isolation, and deletion paths.

## Project Structure

```text
supabase/migrations/00019_create_generations.sql   # table, indexes, RLS, private bucket

backend/app/presets.py                     # presets, provider sizes, composition guidance
backend/app/models/generation.py
backend/app/routes/generations.py          # API; DB calls run in the thread pool
backend/app/services/generation_store.py   # queue, leases, claims, ownership, asset lock
backend/app/services/generation_storage.py # private bucket upload/sign/delete
backend/app/services/image_generation.py   # OpenAI call and PNG processing
backend/app/services/brand_deletion.py     # extended to clear generated assets
backend/app/worker.py                      # worker loop, liveness, structured logs
backend/app/log.py                         # shared allowlist JSON log formatter
backend/app/config.py                      # privilege assertions include generations

backend/tests/contract/test_generations.py
backend/tests/unit/test_generation_worker.py
backend/tests/unit/test_image_generation.py
backend/tests/unit/test_generation_storage.py
backend/tests/unit/test_generation_container.py
backend/tests/integration/test_generation_queue.py

frontend/lib/generations.ts
frontend/components/generation-result.tsx
frontend/app/(dashboard)/brands/[brandId]/generate/page.tsx
frontend/app/(dashboard)/brands/[brandId]/history/page.tsx
frontend/app/(dashboard)/brands/[brandId]/page.tsx   # navigation entry points
frontend/playwright.generations.config.ts
frontend/tests/e2e/generations.spec.ts

scripts/container-entrypoint.sh            # supervises the worker
scripts/container-healthcheck.sh           # checks the worker heartbeat file
docs/generations.md                        # runbook and API reference
docs/generation-verification.md            # verification evidence
```

**Structure Decision**: Follow the existing route/model/store/storage separation. Run the worker as a third supervised process in the existing container instead of a new deployable, keeping one image per the Dockerization spec.

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|
| Roadmap Phase 6 checkpoint (both providers, all logo modes) not met | Ship OpenAI generation first; Gemini and logo processing need their own design | Waiting for both delays the core capability; Gemini behavior is tracked as N/A until integrated |
| No provider filter in the history UI | Only one provider can produce generations | A one-option filter adds UI without function; the API already supports the filter for when Gemini ships |
| Separate worker process and PostgreSQL queue | Calls take up to 3 minutes, are paid, and must survive restarts | In-request generation would tie up HTTP workers and lose paid results on restart; an external queue adds a new service |
| Container stop needs `--stop-timeout 300` | The worker finishes its current job on SIGTERM (up to ~4.5 minutes) | Docker's 10-second default kills in-flight jobs, which then end as `GENERATION_INTERRUPTED` after being billed |
