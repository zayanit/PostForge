# Contract: Container Healthcheck

Observable behavior contract for the container's combined health status (FR-004,
SC-003). Consumed by the Dockerfile's `HEALTHCHECK` instruction and, indirectly, by the
hosting platform's own readiness/liveness probing.

## Inputs

None from outside the container. The healthcheck script (`scripts/container-healthcheck.sh`)
takes no arguments and reads no environment configuration beyond the fixed internal
addresses of the two in-container processes.

## Behavior

1. `GET http://127.0.0.1:8000/health` (backend, new unauthenticated route)
2. `GET http://127.0.0.1:3000/login` (existing public frontend route — no new route needed)
3. Each request is made with redirects disabled (`--max-redirs 0`), an explicit
   per-request `curl --max-time 2` (so the two sequential requests fit with margin inside
   the shared 5-second `HEALTHCHECK --timeout`, rather than each implicitly assuming the
   full 5s for itself), and its HTTP status code captured explicitly (e.g.
   `curl -s -o /dev/null -w '%{http_code}'`) — the check MUST verify the code falls in the
   `2xx` range itself, rather than relying only on `curl -f`'s default behavior, which
   treats any non-`4xx`/`5xx` response (including a redirect) as success.
4. Exit code `0` (healthy) only if **both** requests return a `2xx` status, with the
   whole script (both requests combined) completing inside the shared 5-second
   `HEALTHCHECK --timeout` budget.
5. Exit code `1` (unhealthy) if either request fails, times out (per-request `--max-time`
   or the overall `HEALTHCHECK --timeout`, whichever trips first), returns a redirect or
   non-2xx status, or the connection is refused (process not listening).

## Explicit non-goals (per spec clarification)

- MUST NOT attempt to reach Supabase or any other external service. A healthy result
  means only "both local processes are up and responding" — nothing about downstream
  dependency availability.
- MUST NOT perform a synthetic end-to-end transaction (e.g., a real login). Liveness only.

## Backend `/health` route contract

- `GET /health`
- No `Authorization` header required (unlike every other backend route).
- Response: `200 OK`, minimal JSON body (e.g., `{"status": "ok"}`), matching the shape
  already used by the existing `GET /` root route in `backend/app/main.py`.
- MUST NOT perform any database or external-service call — it exists purely to prove the
  FastAPI process itself is accepting requests, consistent with the "no external
  dependency" rule above.

## Timing (SC-003)

- `HEALTHCHECK` is configured with `--interval=10s --timeout=5s --start-period=30s
  --retries=3`.
- Container reports healthy within 60 seconds of start under normal conditions — the
  30-second `--start-period` means early, expected-transient failures during startup
  don't count against the container, and *any* single successful check, including one
  that happens during the start period itself (not only after it elapses), immediately
  reports healthy.
- Reports unhealthy only after 3 consecutive failed checks — worst case approximately 45
  seconds after either process actually stops responding (3 checks, each up to the 5s
  `--timeout`, spaced 10s `--interval` apart), not after a single failed check (Docker's
  `HEALTHCHECK` requires `--retries` consecutive failures before flipping status).
