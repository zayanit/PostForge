# Research: Image Generation (OpenAI-first release)

Recorded retroactively; each decision reflects the implementation in `64d2a48` and PR #24.

## Job queue

- **Decision**: Use the `generations` table as the queue. Claims use `FOR UPDATE SKIP LOCKED`, lock the brand row before its jobs, and pick the brand whose oldest claimable job has waited longest.
- **Rationale**: No new infrastructure; job state, history, and ownership live in one row under RLS. Ordering by oldest job (not oldest brand) prevents one tenant's backlog from starving others.
- **Alternatives**: An external queue (Redis, SQS) adds a service and a second source of truth. Ordering by `brands.created_at` was the initial implementation and starved newer brands.

## Leases and fencing

- **Decision**: A claim sets a random `lease_token` and a five-minute `lease_expires_at`, renewed every 15 seconds. Every write after the claim (`heartbeat`, `begin_upload`, `finish`) matches on the token, requires an unexpired lease, and requires the brand to still be `active`.
- **Rationale**: A worker that stalls, loses its lease, or races a brand deletion cannot publish.
- **Alternatives**: Holding a row lock for the whole job would keep a transaction open across a three-minute network call.

## No automatic provider retries

- **Decision**: Provider failures are recorded with a fixed error code; nothing is retried. Recovery after a crash publishes an already-uploaded image or fails the job with `GENERATION_INTERRUPTED`.
- **Rationale**: Calls are billed to the user's own key, so a retry must be an explicit user choice.

## Uncertain uploads

- **Decision**: Before uploading, the worker sets `upload_fence_until` (five minutes). If the upload outcome is unknown, the job stays `processing`; recovery waits out the fence, then checks the deterministic object path. Brand deletion refuses to proceed while a fence is active.
- **Rationale**: A Storage write can commit after the client times out. The fence stops deletion from racing a late write and stops recovery from failing a job whose image may still land.

## Per-brand asset lock

- **Decision**: Publication, generation deletion, and brand deletion take a transaction-scoped advisory lock per brand (`pg_try_advisory_xact_lock`). User-facing requests fail fast with a retryable 409. The worker retries for up to 60 seconds without blocking its event loop.
- **Rationale**: Deleting an image and publishing another for the same brand must not interleave with brand-prefix cleanup. The worker waits because giving up would discard an image the user already paid for; that was a bug in the initial implementation.
- **Alternatives**: A blocking lock inside a request handler would tie up the server while it waits.

## Sizes and cropping

- **Decision**: Request `1024x1024`, `1536x1024`, or `1024x1536` by orientation, then center-crop and resize with Pillow to the exact preset. The prompt ends with a composition note giving the final size and the share of the canvas that survives the crop (rounded down).
- **Rationale**: The provider supports a few fixed sizes, but presets range from 4:1 to 9:16. Without the note, wide presets such as LinkedIn Banner (37% of the height kept) cut off subjects and text.
- **Known limitation**: YouTube Banner (2560x1440) is upscaled about 1.67x. Larger provider sizes were not adopted without confirming `gpt-image-2` supports them.

## Image delivery

- **Decision**: A private bucket with five-minute signed URLs, issued only after an ownership check. The UI renews links every four minutes and fetches a fresh link before downloading. The history page polls only in-progress items and reloads the full list once when one finishes.
- **Rationale**: Generated images are private brand assets. Re-signing every image on each poll changes every URL and forces the browser to download every image again.

## Idempotent submission

- **Decision**: An `Idempotency-Key` UUID is required, unique per brand, together with a SHA-256 hash of the normalized request. Same key and same input return the existing job; same key and different input return 409. The UI keeps the key across retries of an unchanged submission.
- **Rationale**: A submission whose response is lost must be safely retryable without creating a second paid job.

## Worker operations

- **Decision**: The worker writes a liveness file every 15 seconds from a task that never touches the database; the healthcheck requires it to be under 60 seconds old. On SIGTERM the worker claims nothing new and finishes its current job; containers run with `--stop-timeout 300`. Logs go through the shared allowlist JSON formatter: one `generation.job_finished` line per job (generation ID, brand ID, outcome, error code, duration) and exception class names, never exception text.
- **Rationale**: Health must not depend on Supabase (Dockerization healthcheck contract). Exception text can contain keys, prompts, SQL, or signed URLs.

## Request handling

- **Decision**: Generation routes are `async` (Storage calls are async) and run every synchronous database call, including the asset lock, in the thread pool. History reads check ownership without locking the brand row.
- **Rationale**: Synchronous queries on the event loop would stall every request on the process during a slow query or lock wait.
