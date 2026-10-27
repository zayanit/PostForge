# Contract: Generation Worker

Process: `python -m app.worker` in the container (`python -m backend.app.worker` locally), supervised by `scripts/container-entrypoint.sh` alongside the API and frontend.

## Startup

1. Configure the shared allowlist JSON log formatter.
2. Assert the backend database role's privileges; exit non-zero if they are missing. The entrypoint restarts the worker.
3. Start the liveness task, then the claim loop.

## Claim loop

- Claim one job at a time. With nothing to claim, sleep 2 seconds.
- A claim picks the active brand whose oldest claimable job (pending, or processing with an expired lease, not `cleanup_required`) has waited longest, then that brand's oldest such job. It sets a new lease token and a five-minute lease. Jobs whose lease had expired are processed in recovery mode.
- While a job runs, renew its lease every 15 seconds. Renewal stops if the lease is lost; a database error during renewal is logged and retried.

## Processing a job

1. Read the decrypted key for the snapshotted key ID. If it is no longer usable, fail with `OPENAI_KEY_REQUIRED`.
2. Re-check the lease and brand, then call OpenAI once (180-second deadline).
3. Take the brand's asset lock, retrying every 0.5 seconds for up to 60 seconds. If it is still busy, leave the job for recovery.
4. Under the lock: re-check the lease and brand, set the upload fence, upload the PNG, and finish as `succeeded`.
5. If the upload outcome is unknown, leave the job `processing` for recovery.

## Recovery mode

Under the asset lock: if the lease or brand is no longer valid, stop. If an upload fence is still active, stop and let a later claim retry. Otherwise publish the object if it exists, or fail the job with `GENERATION_INTERRUPTED`. Recovery never calls the provider.

## Liveness

Write the current time to `GENERATION_WORKER_HEARTBEAT` (default `/tmp/postforge-worker-heartbeat`) every 15 seconds, from a task that never touches the database. The container healthcheck requires the file to be under 60 seconds old. Remove the file on exit.

## Shutdown

On SIGTERM or SIGINT, claim nothing new, finish the current job, then exit. A job can take up to about 4.5 minutes, so containers must run with `--stop-timeout 300` (or an equal platform grace period). A job killed mid-flight is recovered as `GENERATION_INTERRUPTED`.

## Logging

All records go through the allowlist formatter (`backend/app/log.py`); messages and exception text are never written.

| Event | Level | Fields |
|---|---|---|
| `generation.worker_started` / `generation.worker_stopped` | INFO | — |
| `generation.job_finished` | INFO, or WARNING when `outcome` is `failed` | `generation_id`, `brand_id`, `recovery`, `outcome`, `code`, `provider_request_id`, `duration_ms` |
| `generation.lease_renewal_failed` | WARNING | job IDs, `error_type` |
| `generation.worker_error` | ERROR | job IDs when known, `error_type` |
| `generation.heartbeat_write_failed` | ERROR | `error_type` |
| `generation.worker_fatal` | ERROR | `error_type` |

`outcome` is one of `succeeded`, `failed`, `recovered`, `lease_lost`, `upload_pending`, `upload_uncertain`, or `asset_busy`.
