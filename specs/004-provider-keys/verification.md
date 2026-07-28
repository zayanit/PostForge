# Provider Keys Verification

**Date**: 2026-07-28

## Automated Results

- Backend suite: 226 passed with no skipped tests.
- Provider-key RLS, catalog, Data API, backend-table, and Vault checks: 9 passed.
- Supabase schema lint: no errors at warning level.
- Frontend ESLint, TypeScript, and production build: passed.
- Provider-key Playwright flow: 2 passed.
- Production `linux/amd64` container image build: passed.
- Focused secrecy suites after diagnostic-boundary hardening: 172 passed.

The automated suites cover safe add/list behavior, deterministic OpenAI and Gemini
classification, ownership and RLS, Vault isolation, activation and validation races,
idempotent and ambiguous database outcomes, individual cleanup retry, token-owned
Storage operations, multi-page cleanup, brand hard deletion, and auth-user deletion
restrictions.

## Environment Blocker

Quickstart Scenario 2 steps 8-10 require user-supplied disposable OpenAI and Gemini
credentials entered through the UI. No disposable provider credentials were available
in this verification environment. Those checks were not simulated or treated as
passing: real official model-list acceptance and the associated live-log review remain
blocked.

Because real-provider verification is applicable to this feature, Quickstart Scenario 2,
the complete six-scenario run, and the final constitutional Definition of Done remain
open until both providers return `valid` through the UI and the live logs pass review.

## Applicability

- Brand Kit zero-answer and completed-kit checks are not applicable because Brand Kit
  does not exist and provider-key behavior does not read or depend on it.
- Generation lifecycle, platform preset, and PNG-output checks are not applicable
  because image generation does not exist and provider-key operations perform no
  generation.
- OpenAI and Gemini behavior is applicable because this feature introduces both
  integrations; deterministic checks pass, but the real-provider gate above remains.
