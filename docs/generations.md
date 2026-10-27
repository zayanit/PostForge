# Image generation release

The first generation release supports OpenAI `gpt-image-2`, one medium-quality PNG
per request, the 13 presets in the implementation roadmap, and brand-scoped history.
Generation works with empty, partial, and complete Brand Kits. Gemini, logo processing,
batch generation, cancellation, billing, and automatic paid retries are deferred.

## Setup and deployment

Apply the existing migrations and `00019_create_generations.sql` to a local Supabase
stack before starting the upgraded services. For an existing local stack:

```bash
supabase migration up --local
```

The migration creates the queue/history table with forced RLS, backend-controlled
writes, owner-scoped reads, and a private `generation-assets` bucket. It does not
change the existing public logo bucket. If using a dedicated backend database role,
grant it SELECT/INSERT/UPDATE/DELETE on `public.generations`, alongside the existing
application/Vault privileges. API and worker startup validate those privileges.

Start the API, frontend, and worker in separate terminals with the existing environment
settings. The worker uses the same backend credentials; no application-wide OpenAI
key is required. Owners add an OpenAI key in their brand's provider settings.

```bash
make dev-backend
make dev-frontend
make dev-worker
```

For Windows PowerShell, install dependencies from the repository root:

```powershell
py -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
Push-Location frontend
npm ci
Pop-Location
```

Import your existing `backend/.env` into each backend/worker terminal. The following
loader supports the plain KEY=VALUE format used by `.env.example`; it never prints
values. Supply the actual required values in the ignored file first.

```powershell
Get-Content backend/.env | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
    }
}
backend/.venv/Scripts/python.exe -m uvicorn backend.app.main:app --reload
```

In another terminal, import the environment again and run:

```powershell
backend/.venv/Scripts/python.exe -m backend.app.worker
```

Configure `frontend/.env.local` using the README, then run `npm run dev` from
`frontend`. The default worker heartbeat file is `postforge-worker-heartbeat` in
the OS temporary directory. Override it with `GENERATION_WORKER_HEARTBEAT` if needed.

The production container supervises all three processes, restarts a failed child,
and checks the worker heartbeat along with the two HTTP services. Shutdown stops
accepting new jobs and lets the current provider attempt finish; a forced shutdown
leaves a recoverable processing record. Apply migrations before deploying the image.
If a release must be rolled back, retain the additive schema and stored images;
do not deploy an old deletion implementation against brands with generated assets.

## API and behavior

All endpoints require the existing authenticated session and verify brand ownership.
They use the existing safe error envelope. Internal context, credential IDs, worker
leases, and storage paths are excluded from responses and logs.

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | `/api/v1/brands/generation-presets` | Canonical preset labels and dimensions |
| POST | `/api/v1/brands/{id}/generate` | Persist a job; return 202 with its record |
| GET | `/api/v1/brands/{id}/generations` | Paginated newest-first history |
| GET | `/api/v1/brands/{id}/generations/{generationId}` | Current state and a fresh image link |
| DELETE | `/api/v1/brands/{id}/generations/{generationId}` | Permanently remove the PNG and record |

Submission requires an `Idempotency-Key` UUID header and a JSON object containing
`prompt` (3–4,000 characters) and `platform_preset`. Optional provider/model values
must be `openai`/`gpt-image-2`; other models, providers, and extra fields are rejected.
The same ID and normalized input return the existing job, including after key changes.
Reusing an ID with different input returns 409. Deleting a generation also removes
its submission receipt; a later reuse of that ID is a new submission.

History accepts `page` (default 1), `per_page` (default 20, maximum 100), `status`,
and `provider`. Gemini filtering returns an empty list in this release. The frontend
provides status filtering, preview, download, pagination, and confirmed deletion.

Brand context and the selected key ID are snapshotted at submission. The worker
checks that the key is still usable before decrypting it. The provider uses standard
square/landscape/portrait sizes; Pillow center-crops and resizes to exact product
dimensions, then writes PNG. The integration follows the
[official OpenAI Images API](https://developers.openai.com/api/reference/resources/images/methods/generate),
including PNG output and omission of the unsupported legacy `response_format` field.

Images use `brands/{brandId}/generations/{generationId}.png` in the private bucket.
The backend checks ownership before signing five-minute URLs. A signed URL is a
temporary bearer link: anyone holding it can use it until expiry. The UI refreshes
links every four minutes and obtains a fresh link before downloading. Do not log
signed URLs or treat them as permanent identifiers.

## Worker recovery and deletion

The PostgreSQL queue persists `pending`, `processing`, `succeeded`, and `failed`
states. Atomic claims use SKIP LOCKED and fresh lease tokens. Each worker processes
one provider request at a time, heartbeats every 15 seconds, and leases jobs for
five minutes. Provider calls have a three-minute total deadline and are not retried.

Pending work resumes after restart. Expired processing work is reclaimed with a
new token. Recovery checks the deterministic storage path: an existing image is
published; otherwise the record fails with `GENERATION_INTERRUPTED`. Recovery never
calls the provider. An interrupted request may have incurred provider charges even
when no result can be recovered; creating a new attempt is an explicit user action.

Worker publication and deletion share a PostgreSQL advisory lock per brand. They
recheck state and lease ownership before publication. Before an upload, the worker
persists a five-minute uncertainty fence. If upload completion is unknown, the job
stays processing for reconciliation; brand deletion remains fenced and returns a
retryable cleanup error until that window expires. A retry then clears both buckets
before deleting database/Vault dependencies. Stale workers cannot publish results
after the brand is fenced.

Processing generations return 409 on individual deletion. Pending jobs are fenced
atomically against claims. Storage deletion failures preserve the record with
`cleanup_required=true`; owners retry from history. Successful deletion physically
removes the object and record. Brand deletion removes generated images as well as
logos and provider keys.

## Verification

Run the self-contained suites without real credentials or paid requests:

```powershell
backend/.venv/Scripts/python.exe -m pytest -q backend/tests/contract backend/tests/unit backend/tests/integration/test_generation_queue.py
Push-Location frontend
npm run lint
npx tsc --noEmit
npx playwright install chromium
npx playwright test --config playwright.generations.config.ts
npm run build
Pop-Location
```

`test_generation_queue.py` starts a disposable PostgreSQL instance using the
development-only `embedded-postgres` package. It applies the actual generation
migration with minimal Auth/Vault/Storage scaffolds; it tests real SQL, locks, queue
recovery, RLS, and deletion. It does not certify the real Supabase Vault or Storage
services. The browser suite owns a local auth fixture and mocks application/provider
responses, so it does not generate paid images.

Before release, also run the complete existing backend/browser suites against a
running local Supabase stack, build the Linux container, kill/restart its worker,
and run a disposable live BYOK generation. Confirm exact PNG dimensions, link expiry,
cross-owner denial, revoked-key behavior, and physical cleanup in real Storage.
Record outcomes separately; mocked tests do not substitute for these checks.

Current execution results are recorded in `generation-verification.md`.

## Constitution check

- Brand-scoped ownership, forced RLS, client write denial, secret boundaries, and
  physical generation/brand deletion are covered by contract and isolated PostgreSQL
  tests. Real Supabase Storage/Vault verification remains a release gate.
- Empty, partial, and complete Brand Kit snapshots are covered because generation
  reads Brand Kit data.
- OpenAI behavior, the generation lifecycle, explicit preset selection, and exact PNG
  output are applicable and covered by deterministic API/worker/browser tests.
- Gemini generation is deferred and is not changed by this feature; existing Gemini
  key management remains in place. Logo processing is outside this first release.
- No billing, sharing, soft deletion, or client-side provider calls are introduced.
