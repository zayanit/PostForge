# Quickstart: Validate Dockerization

Run these scenarios end-to-end against a real build to prove the feature works, matching
the acceptance scenarios in `spec.md`. See `contracts/healthcheck.md` and
`contracts/entrypoint.md` for the exact behavior each step is checking.

## Prerequisites

- Docker installed and running.
- A reachable Supabase project (local `supabase start` or hosted) with its URL and keys
  on hand — this container talks to Supabase exactly like the non-containerized app does.
- From repo root, on this feature's branch.

## Scenario 1: Build and run as one container (User Story 1)

```bash
docker build --platform linux/amd64 -t postforge:local .

docker run --rm -p 3000:3000 \
  -e SUPABASE_URL=... \
  -e SUPABASE_SECRET_KEY=... \
  -e SUPABASE_JWT_SECRET=... \
  -e NEXT_PUBLIC_SUPABASE_URL=... \
  -e NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=... \
  postforge:local
```

(`--platform linux/amd64` matches the declared deployment target — see `plan.md` §
Technical Context — and keeps the local build consistent with what's deployed even when
building on a different host architecture, e.g. Apple Silicon.)

**Expected**: Build completes without error. Container starts; visiting
`http://localhost:3000` in a browser reaches the app. Sign in, view, and edit a profile
exactly as in local (non-containerized) development — confirms both frontend and backend
are reachable through the single exposed port (FR-001, FR-002, spec Acceptance Scenario
1.1–1.2).

Stop the container (`Ctrl+C` or `docker stop`) and confirm it exits promptly with no
lingering processes (`docker ps` shows nothing for this container; spec Acceptance
Scenario 1.3).

## Scenario 2: Backend is not publicly reachable (FR-002, SC-002)

```bash
docker run -d --name pf-noport --platform linux/amd64 -p 3000:3000 \
  -e SUPABASE_URL=... \
  -e SUPABASE_SECRET_KEY=... \
  -e SUPABASE_JWT_SECRET=... \
  -e NEXT_PUBLIC_SUPABASE_URL=... \
  -e NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=... \
  postforge:local

curl -sf http://localhost:8000/health && echo "FAIL: backend reachable" || echo "OK: backend not reachable"
docker port pf-noport
docker rm -f pf-noport
```

**Expected**: The `curl` to port 8000 fails (connection refused) — only port 3000 is
published. `docker port pf-noport` shows exactly one mapped port.

## Scenario 3: Combined healthcheck reports accurately (User Story 2)

```bash
docker run -d --name pf-health --platform linux/amd64 -p 3000:3000 \
  -e SUPABASE_URL=... \
  -e SUPABASE_SECRET_KEY=... \
  -e SUPABASE_JWT_SECRET=... \
  -e NEXT_PUBLIC_SUPABASE_URL=... \
  -e NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=... \
  postforge:local
watch docker inspect --format='{{.State.Health.Status}}' pf-health
```

**Expected**: Status is `starting`, then flips to `healthy` within 60 seconds (SC-003),
per the configured `--interval=10s --timeout=5s --start-period=30s --retries=3`.

Killing the backend process outright (`kill`) lets the entrypoint restart it right away,
which can race with the healthcheck and make the unhealthy transition hard to observe
deterministically. Instead, pause it in place first:

```bash
docker exec pf-health sh -c "kill -STOP \$(pgrep -f uvicorn)"
```

**Expected**: Because the paused process doesn't exit, the entrypoint does not restart it
yet, but it also stops answering the healthcheck — status flips to `unhealthy` after 3
consecutive failed checks (worst case ~30-35s at the configured interval, not the very
next check). Now let it actually exit so the entrypoint's crash-restart takes over:

```bash
docker exec pf-health sh -c "kill -CONT \$(pgrep -f uvicorn) && kill \$(pgrep -f uvicorn)"
```

**Expected**: Status returns to `healthy` shortly after (once the restarted process passes
its next check) — because the entrypoint restarted the killed backend process in place
(FR-003a), without the container itself restarting (`docker inspect --format=
'{{.State.StartedAt}}' pf-health` is unchanged throughout the whole scenario).

Repeat both steps against the frontend process (`pgrep -f "next start"`) instead — same
expected transitions.

```bash
docker rm -f pf-health
```

## Scenario 4: No secrets baked into the image (FR-005, SC-005)

The real risk this checks for is a local `backend/.env` (or similar) file being present
in the build context and accidentally getting copied into a layer despite `.dockerignore`
— not a `docker run -e` value, which by construction can never appear in something built
earlier by `docker build`. So the test plants a distinctive fake secret in a local env
file *before building*, then confirms it's absent from the built image:

```bash
QS_TEST_SECRET="sb_secret_quickstart_test_do_not_reuse_$(date +%s)"
cp backend/.env backend/.env.quickstart-backup 2>/dev/null || true
printf '\nSUPABASE_SECRET_KEY=%s\n' "$QS_TEST_SECRET" >> backend/.env

docker build --platform linux/amd64 -t postforge:local-secret-test .

# restore/remove the local .env so this test value doesn't linger
mv backend/.env.quickstart-backup backend/.env 2>/dev/null || rm -f backend/.env

# 1. Build-time layers: the value must never have been baked in during `docker build`
docker history --no-trunc postforge:local-secret-test | grep -F "$QS_TEST_SECRET" \
  && echo "FAIL: secret value found in image history" || echo "OK: not in image history"

# 2. Exported filesystem: catches a value copied into a file, not just an ENV/ARG layer
container_id=$(docker create postforge:local-secret-test)
docker export "$container_id" | tar -xO 2>/dev/null | grep -F "$QS_TEST_SECRET" \
  && echo "FAIL: secret value found in image filesystem" || echo "OK: not in image filesystem"
docker rm "$container_id"
docker rmi postforge:local-secret-test
```

**Expected**: Both checks report "OK" — `.dockerignore` (T001) excludes `backend/.env`
from the build context entirely, so `$QS_TEST_SECRET` never reaches any build layer or
the image's filesystem, even though it was present locally at build time.

**Limitation**: This only proves *this specific planted value* isn't present — it's a
targeted regression check for "a local env file doesn't leak into the build," not a
general secret-scanner. It won't catch an unrelated hardcoded credential embedded some
other way. A dedicated secret-scanning tool is out of scope for this quickstart.

## Scenario 5: Non-root runtime user (FR-006)

The image's `ENTRYPOINT` runs `tini` + the container entrypoint script, so a plain
`docker run postforge:local sh -c "whoami"` would just pass `sh -c "whoami"` as extra
arguments to that entrypoint instead of replacing it. Override the entrypoint explicitly:

```bash
docker run --rm --entrypoint sh postforge:local -c "whoami && id -u"
```

**Expected**: Prints a non-root username (not `root`) and a non-zero UID.

## Scenario 6: Documentation walkthrough (User Story 3)

Have someone unfamiliar with this feature follow `docs/docker.md` from a clean checkout,
using only what's written there (no verbal help). They should reach a running, healthy
container and understand how to supply configuration/secrets without being told to bake
them into the image (spec Acceptance Scenario 3.1–3.2).
