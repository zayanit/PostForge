# Generation release verification

Recorded 2026-10-27 on Windows. No live paid
provider generation, production migration, or deployment was performed.

## Passing checks

| Check | Result |
| --- | --- |
| Backend contracts, units, and isolated PostgreSQL generation suite | 271 passed |
| Generation browser suite plus visitor navigation/session regressions | 10 passed |
| Frontend ESLint | Passed |
| Frontend TypeScript (`tsc --noEmit`) | Passed |
| Production Next.js build | Passed; generator/history routes included |
| Ruff on new Python implementation/tests | Passed |
| Shell syntax for entrypoint and healthcheck | Passed |
| Supervisor restart/shutdown and fresh/stale heartbeat checks | 3 passed, included above |
| Hash-checked backend dependency installation on Windows | Passed |
| Desktop/mobile screenshot inspection | Passed; mobile has no horizontal overflow |

Backend commands were run from the repository root with an isolated Python 3.12
virtual environment and the repository's locked runtime dependencies. The production
image still targets Python 3.11. New Python sources were checked for 3.11 syntax.

```powershell
python -m pytest -q backend/tests/contract backend/tests/unit backend/tests/integration/test_generation_queue.py
```

The generation queue tests use a real disposable PostgreSQL 18.6 server. They apply
the actual generation migration, with minimal test scaffolds for Supabase-managed
schemas. Coverage includes simultaneous idempotent submissions, conflicting reuse,
empty/partial/complete kit snapshots, atomic claims, expired leases, stale publication,
active-job deletion conflicts, pending-job deletion, advisory-lock exclusion, forced
RLS, owner isolation, client write denial, key removal, worker publication/history,
physical brand cleanup, and uncertain-upload fencing.

Provider/storage unit tests use deterministic HTTP transports. All 13 PNG output
dimensions and center cropping pass. Provider failures are not retried, raw error
bodies are discarded, malformed images fail safely, and recovery does not call the
provider. Private URL signing requests a 300-second expiry.

```powershell
Push-Location frontend
npm run lint
npx tsc --noEmit
npx playwright test --config playwright.generations.config.ts
npm run build
Pop-Location
```

The browser run used the suite's mock Auth/API/image fixtures and Chromium, with the
Next.js test server managed separately through `PLAYWRIGHT_EXTERNAL_SERVER=1` to
avoid a Windows managed-server teardown hang. The equivalent managed-server setup
is supplied by the dedicated Playwright configuration. Seven new generation checks
and three existing visitor checks passed. Browser checks cover reload recovery,
download, permanent deletion/cancellation/retry, missing keys, incomplete kits,
idempotent explicit retry, safe provider failures, signed-link refresh, mobile layout,
and unauthenticated redirects.

## Full suite and remaining release gates

The full backend command was attempted after implementation:

```powershell
python -m pytest -q --tb=no backend/tests
```

At that run it reported **273 passed, 21 skipped, 3 failed, and 25 setup errors**.
The final complete-kit snapshot test was added afterward and passes in the focused
271-test run above. The full suite is not certified as passing.

This environment has no configured `DATABASE_URL` or running Supabase stack.
Contract test setup supplies example Supabase settings; those are not usable for
real Auth/Storage/Vault integrations. The three failures were checked individually:
the login-lockout case cannot pass database startup validation without a database;
profile-RLS and signup-profile cases cannot reach real Supabase Auth. The 25 setup
errors are existing provider-key integration prerequisites requiring `DATABASE_URL`.
Other real-stack tests skip without their required settings. These tests were not
weakened or marked complete to hide the missing infrastructure.

Before release:

- Apply migration 00019 locally and run the complete existing backend/browser
  suites against real Supabase Auth, Vault, PostgreSQL, and Storage. In particular,
  verify anonymous/cross-owner object denial, actual signed URL expiry, and deletion
  from both storage buckets.
- Build and run the Linux/amd64 container with Docker, then verify worker restart,
  forced termination/recovery, heartbeat health, and shutdown. Docker is unavailable
  here; the passing shell lifecycle tests use controlled child processes.
- Perform a disposable live OpenAI BYOK generation and confirm PNG dimensions,
  revoked-key handling, safe provider errors, download, and physical cleanup.
- Run production Python 3.11 validation in the Linux image. Python 3.12 Windows
  execution and 3.11 syntax compatibility do not replace that check.

The deployment/runbook and feature task checklist retain these gates as incomplete.
