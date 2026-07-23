# Contract: Container Entrypoint & Process Supervision

Observable behavior contract for `scripts/container-entrypoint.sh`, run under `tini` as
the container's PID 1 (FR-003, FR-003a).

## Startup

1. Start the backend (`uvicorn`, bound to `127.0.0.1:8000` only — never the public
   interface, per FR-002) as a background job; record its PID.
2. Start the frontend (`next start`, bound to the container's public port) as a
   background job; record its PID.
3. Enter the supervision loop (see below).

## Supervision loop (crash-restart behavior)

- Block on `wait -n` for either background job to exit, capturing its exit status
  explicitly (the script runs under `set -euo pipefail`, so the status must be captured
  in a way that doesn't itself trip `set -e` — e.g. `wait -n; status=$?` inside an `if`/
  guarded context, never a bare `wait -n` whose nonzero return would exit the entrypoint).
- If a shutdown has been requested (see Shutdown below), exit the loop instead of
  restarting anything.
- Otherwise, first determine **which** of the two saved PIDs is no longer running (e.g.
  `kill -0 "$pid" 2>/dev/null`) — this PID lookup MUST happen before any restart decision,
  since it's what identifies which process needs restarting. Log that it exited (exit
  code, which process — no environment variable values or secrets, per Security Rules),
  then restart **only that process**, replacing its saved PID with the new one.
- The other process and the container itself are left untouched — this is the
  distinguishing behavior from "the container as a whole crashes and the host restarts
  it," which was explicitly rejected during spec clarification.
- Loop indefinitely.

## Shutdown

- On receiving `SIGTERM` or `SIGINT` (forwarded by `tini`), set a shutting-down flag,
  forward the same signal to both child processes, and wait for both to exit before the
  entrypoint itself exits.
- MUST NOT leave orphaned processes after the container reports stopped (FR-003), even if
  the signal arrives mid-startup before both processes have finished coming up.

## Explicit non-goals

- MUST NOT attempt to restart a process more than the container's own lifetime allows —
  there is no backoff/give-up policy in scope; a process crash-looping is a signal for
  the operator to notice via repeated healthcheck failures (see `healthcheck.md`), not
  something the entrypoint tries to paper over indefinitely.
- MUST NOT log secret environment variable values at any point (startup, restart, or
  shutdown) — only process names/PIDs/exit codes, consistent with the constitution's
  Security Rules (no keys, tokens, or PII in logs).
