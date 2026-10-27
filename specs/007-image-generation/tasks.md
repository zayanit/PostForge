# First image generation release

Implements the approved OpenAI-first release. Contract and operational details are
in `docs/generations.md`; execution evidence is in `docs/generation-verification.md`.

- [x] Add generation/history schema, forced RLS, private bucket, and backend grants.
- [x] Implement idempotent submission, fixed provider/model, context snapshots,
  pagination, detail, signed retrieval, and permanent deletion APIs.
- [x] Implement PostgreSQL claims, worker leases/heartbeats, bounded provider calls,
  restart reconciliation without repeating paid requests, and stale-token fencing.
- [x] Implement OpenAI PNG processing and exact center-cropped preset dimensions.
- [x] Fence worker uploads and brand deletion; retain retryable cleanup on failure.
- [x] Add generator/history navigation, progress recovery, image previews/downloads,
  refreshed signed links, status filtering, pagination, and confirmed deletion.
- [x] Add container supervision/health checks, local worker commands, dependency
  hashes, Windows instructions, and roadmap updates.
- [x] Verify deterministic provider/storage cases, real PostgreSQL concurrency/RLS,
  container shell lifecycle, browser journeys, mobile layout, lint, types, and build.
- [ ] Verify real Supabase Auth/Vault/Storage integrations with the full existing suite.
- [ ] Build/run the Linux container and verify worker restart under Docker.
- [ ] Run a disposable live OpenAI BYOK generation, signed-link expiry, and cleanup.

The last three items require runtime services/credentials unavailable in the
implementation environment. They are release gates, not completed checks.
