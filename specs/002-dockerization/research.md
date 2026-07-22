# Phase 0 Research: Dockerization

No `NEEDS CLARIFICATION` markers remain in the Technical Context — the two open design
questions this feature has (crash-restart scope, healthcheck depth) were already resolved
in `spec.md` via `/speckit-clarify`. The research below covers implementation-level
decisions needed to satisfy those clarified requirements, not open unknowns about scope.

## Decision 1: Base images and multi-stage layout

**Decision**: Multi-stage build — a `node:20-slim` stage builds the Next.js frontend
(`npm ci && npm run build`), a `python:3.11-slim` stage installs backend dependencies
(`pip install -r requirements.txt`), and the final runtime stage is `python:3.11-slim`
with Node.js 20 installed alongside it (to run `next start`), copying in the built
frontend (`.next/`, `node_modules` production deps, `public/`) and the backend's
installed site-packages + app code.

**Reproducibility policy (FR-009), stated explicitly per dependency source**:
- **Base images**: pinned by immutable digest, not just a version tag — e.g.
  `node:20-slim@sha256:<digest>` and `python:3.11-slim@sha256:<digest>`. A tag like
  `20-slim` can be repointed to a new underlying image at any time; only the digest
  guarantees the same bytes on every build.
- **Python dependencies**: `backend/requirements.txt` currently pins ranges
  (e.g. `fastapi>=0.115,<1`), which is not sufficient for byte-for-byte reproducibility on
  its own. The backend dependency stage installs from a generated, hash-verified lock file
  (`pip-compile --generate-hashes` output, or equivalent) via
  `pip install --require-hashes -r <lockfile>`, so the exact resolved version and package
  hash are fixed, not just the range.
- **`tini` and apt-installed packages**: installed with an explicit version pin
  (e.g. `apt-get install -y --no-install-recommends tini=<pinned-version>`), not a bare
  `apt-get install tini` that resolves to whatever the base image's package index currently
  serves.

**Rationale**: The runtime stage must contain *both* a Node runtime (for `next start`)
and a Python runtime (for `uvicorn`), since both processes run inside the same container
per FR-001. Building each app in its own stage keeps build-only tooling (full
`node_modules` dev deps, pip build caches) out of the final image, keeping it smaller and
reducing what an attacker could extract from a shipped layer. `-slim` (Debian-based)
variants are chosen over Alpine because: (a) `psycopg2-binary` (already a backend
dependency) is glibc-built and painful on musl/Alpine without extra build tooling, and
(b) the entrypoint's crash-restart supervisor (Decision 2) needs bash's `wait -n`, which
Alpine's default `dash` shell lacks.

**Alternatives considered**:
- *Alpine-based images*: smaller, but reintroduces the psycopg2/musl friction already
  worked around during local Supabase testing (see `001-user-auth-profile`'s
  `requirements.txt` fix), and lacks bash by default. Rejected — the size savings aren't
  worth reopening a dependency problem already solved once.
- *Two separate containers (frontend + backend) behind a shared network*: this is what
  Bunny Magic Container's single-image model explicitly rules out (per
  `docs/implementation-plan.md` § Architecture Overview and Principle III). Rejected —
  contradicts the fixed hosting constraint, not this feature's to relitigate.

## Decision 2: Process supervision and crash-restart behavior

**Decision**: A bash entrypoint script (`scripts/container-entrypoint.sh`), run under
`tini` as PID 1, starts both `uvicorn` (backend, bound to `127.0.0.1` only) and
`next start` (frontend, bound to the public port) as background jobs, saving each one's
PID (`$!`). A supervision loop uses `wait -n` to block until *either* job exits. Because
the script runs under `set -euo pipefail`, and `wait -n` itself returns the exited job's
(possibly nonzero) exit status, the loop captures that status explicitly (e.g.
`wait -n; status=$?` guarded with `|| true` / an `if` test) rather than letting a nonzero
status trip `set -e` and kill the entrypoint. The loop then checks each saved PID with
`kill -0 "$pid" 2>/dev/null` to determine which one is no longer running — identifying the
exited child *before* deciding to restart it — restarts only that one process, and
replaces its saved PID with the new one. A `trap` on `SIGTERM`/`SIGINT` sets a
shutting-down flag and forwards the signal to both children before exiting, so a
deliberate container stop does not get mistaken for a crash and trigger a restart.

**Rationale**: Directly implements the spec clarification (FR-003a): a crashed process is
restarted individually, not by restarting the container. `tini` as PID 1 handles the
signal-forwarding and zombie-reaping duties that a raw bash script run directly as PID 1
would otherwise have to reimplement (bash does not reap orphaned children by default).
This keeps the entrypoint script itself simple: it owns *only* the restart-on-crash
policy, which is the one piece of behavior specific to this feature.

**Alternatives considered**:
- *supervisord*: a purpose-built process supervisor with native "restart this program
  if it exits" config. Rejected as unnecessary weight — it's a full Python-based daemon
  with its own config format, dependency, and log multiplexing model, for a need (two
  processes, restart-in-place) that a ~30-line bash loop covers completely. Adding it
  would violate the project's general preference for the simplest thing that works.
- *s6-overlay*: similar rejection — a fuller init system than two processes warrant.
- *Let the whole container crash and rely on the host restarting it*: this was Option B
  in the clarification question and was explicitly rejected by the user in favor of
  in-place, single-process restart (see spec.md Clarifications).

## Decision 3: Healthcheck mechanism

**Decision**: A single `scripts/container-healthcheck.sh`, invoked by the Dockerfile's
`HEALTHCHECK` instruction, does two local checks against `http://127.0.0.1:8000/health`
(backend, new route) and `http://127.0.0.1:3000/` (frontend — Next.js's own root response
is sufficient evidence of readiness; no new frontend route needed). Each check uses
`curl --silent --show-error --max-redirs 0 --output /dev/null --write-out '%{http_code}'`
and explicitly compares the returned code against the `2xx` range, rather than relying on
`curl -f` alone: `-f` only fails on HTTP status >= 400, so without also capping redirects
(`--max-redirs 0`) and checking the code directly, a `3xx` response would be treated as a
pass even though it isn't the expected `200 OK`. The script exits 0 (healthy) only if both
checks return a `2xx` code, and exits non-zero otherwise. Per the clarification, neither
check touches Supabase or any other external dependency — both are purely "is this local
process answering with a real success status."

**Docker `HEALTHCHECK` timing values**: `--interval=10s --timeout=5s --start-period=30s
--retries=3`. These are the concrete numbers referenced by SC-003 and
`contracts/healthcheck.md`: a container reports `unhealthy` only after 3 consecutive
failed checks post-start-period (worst case ~30-35s after a process actually stops
responding, not "within one check interval" — that phrasing undersold how Docker's
`HEALTHCHECK` retry counter actually works, and has been corrected in the spec and
contract).

**Rationale**: Matches FR-004 and the clarified healthcheck-depth decision exactly: health
reflects only the two in-container processes. Reusing Next.js's existing root response
avoids adding a redundant frontend-only health route; the backend needs one new `/health`
route because none of its existing routes are unauthenticated (every other route requires
a JWT, which a healthcheck script has no way to obtain).

**Alternatives considered**:
- *Have the healthcheck also verify Supabase connectivity (e.g., a DB round-trip)*: this
  was Option B in the clarification question and was explicitly rejected — coupling
  container health to a downstream dependency's transient availability risks flapping the
  container's health status for reasons the container itself can't fix, and complicates
  the crash-restart logic (Decision 2) by conflating "process is down" with "process is up
  but a dependency is unreachable."
- *Separate Docker `HEALTHCHECK` per process*: Docker only supports one `HEALTHCHECK` per
  image/container. Rejected — not possible with a single container, which is exactly why
  a combined script is needed.
