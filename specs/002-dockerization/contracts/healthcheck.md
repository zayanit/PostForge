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
2. `GET http://127.0.0.1:3000/` (frontend root — no new route needed)
3. Exit code `0` (healthy) only if **both** requests succeed (2xx response) within the
   per-check timeout.
4. Exit code `1` (unhealthy) if either request fails, times out, or the connection is
   refused (process not listening).

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

- Container reports healthy within 60 seconds of start under normal conditions
  (`HEALTHCHECK --start-period` should be set accordingly so early, expected-transient
  failures during startup don't count against the container).
- Reports unhealthy within one check interval of either process actually stopping.
