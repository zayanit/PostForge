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
docker build -t postforge:local .

docker run --rm -p 3000:3000 \
  -e SUPABASE_URL=... \
  -e SUPABASE_SECRET_KEY=... \
  -e SUPABASE_JWT_SECRET=... \
  -e NEXT_PUBLIC_SUPABASE_URL=... \
  -e NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=... \
  postforge:local
```

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
docker run --rm -p 3000:3000 -e ... postforge:local &
curl -sf http://localhost:8000/health && echo "FAIL: backend reachable" || echo "OK: backend not reachable"
```

**Expected**: The `curl` to port 8000 fails (connection refused) — only port 3000 is
published. Combined with `docker port <container>` showing exactly one mapped port.

## Scenario 3: Combined healthcheck reports accurately (User Story 2)

```bash
docker run -d --name pf-health -p 3000:3000 -e ... postforge:local
watch docker inspect --format='{{.State.Health.Status}}' pf-health
```

**Expected**: Status is `starting`, then flips to `healthy` within 60 seconds
(SC-003). Then:

```bash
docker exec pf-health sh -c "kill \$(pgrep -f uvicorn)"
```

**Expected**: Status flips to `unhealthy` within one healthcheck interval, then back to
`healthy` shortly after — because the entrypoint restarted the killed backend process in
place (FR-003a), without the container itself restarting (`docker inspect` shows the same
container `StartedAt` timestamp throughout).

Repeat by killing the frontend process (`pgrep -f "next start"`) instead — same expected
transition.

```bash
docker rm -f pf-health
```

## Scenario 4: No secrets baked into the image (FR-005, SC-005)

```bash
docker history --no-trunc postforge:local | grep -i -E "sb_secret|SUPABASE_SECRET_KEY|SUPABASE_JWT_SECRET" \
  && echo "FAIL: secret found in image history" || echo "OK: no secret values in image history"
```

**Expected**: No match — secrets were supplied only at `docker run` time via `-e`, never
present in any build layer.

## Scenario 5: Non-root runtime user (FR-006)

```bash
docker run --rm postforge:local sh -c "whoami"
```

**Expected**: Prints a non-root username (not `root`).

## Scenario 6: Documentation walkthrough (User Story 3)

Have someone unfamiliar with this feature follow `docs/docker.md` from a clean checkout,
using only what's written there (no verbal help). They should reach a running, healthy
container and understand how to supply configuration/secrets without being told to bake
them into the image (spec Acceptance Scenario 3.1–3.2).
