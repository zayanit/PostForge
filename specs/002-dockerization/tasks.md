---

description: "Task list template for feature implementation"
---

# Tasks: Dockerization

**Input**: Design documents from `/specs/002-dockerization/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md (N/A — no entities), contracts/, quickstart.md

**Tests**: No automated test framework is introduced by this feature (see plan.md Technical
Context — "Testing"). Verification is scripted/manual against `quickstart.md`'s 6
scenarios; tasks below reference those scenarios directly instead of separate test files.

**Organization**: Tasks are grouped by user story to enable independent implementation and
testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in each description

## Path Conventions

Infrastructure feature — adds root-level packaging artifacts, not a new `frontend/`/
`backend/` subtree. Paths match `plan.md` § Project Structure: `Dockerfile`,
`.dockerignore`, `scripts/`, `docs/docker.md` at repo root, plus one new backend route.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffolding needed before any Dockerfile/script content can be written

- [ ] T001 Create root `.dockerignore` excluding `node_modules/`, `.venv/`, `.git/`, `.env*` (except `*.example`), `__pycache__/`, `frontend/.next/`, `frontend/test-results/`, `frontend/playwright-report/`, and other local-only artifacts, in `.dockerignore`
- [ ] T002 [P] Create `scripts/container-entrypoint.sh` placeholder (shebang `#!/usr/bin/env bash`, `set -euo pipefail`, executable bit set)
- [ ] T003 [P] Create `scripts/container-healthcheck.sh` placeholder (shebang `#!/usr/bin/env bash`, `set -euo pipefail`, executable bit set)
- [ ] T004 [P] Create `docs/docker.md` skeleton with section headings: Build, Run Locally, Configuration & Secrets, Healthcheck & Restart Behavior, Deploy to Bunny Magic Container, Troubleshooting

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared container substrate every user story's acceptance scenarios run against — must exist before any story can be built or tested

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 Add a Next.js rewrite in `frontend/next.config.js` proxying `/api/:path*` to the internal backend address (`NEXT_SERVER_API_URL`, default `http://127.0.0.1:8000`), so browser requests to the same-origin `/api` path (per `frontend/.env.local.example`'s `NEXT_PUBLIC_API_URL=/api`) reach the backend through the single public port — required for FR-002/SC-002
- [ ] T006 Author `Dockerfile` frontend build stage: pinned `node:20-slim` tag (specific patch version, not `latest`), `npm ci`, `npm run build`, in `Dockerfile`
- [ ] T007 [P] Author `Dockerfile` backend dependency stage: pinned `python:3.11-slim` tag, `pip install --no-cache-dir -r backend/requirements.txt`, in `Dockerfile`
- [ ] T008 Author `Dockerfile` runtime stage: pinned `python:3.11-slim` base, install Node.js 20.x and `tini` via apt, create a non-root user (e.g. `appuser`), copy the built frontend (`.next/`, `public/`, production `node_modules`) and backend app code + installed dependencies, set `WORKDIR`, end with `USER appuser` — in `Dockerfile` (depends on T006, T007)
- [ ] T009 Implement `scripts/container-entrypoint.sh` per `contracts/entrypoint.md`: start the backend (`uvicorn app.main:app --host 127.0.0.1 --port 8000`) and frontend (`next start -p 3000`) as background jobs; run a supervision loop using `wait -n` to detect either process exiting and restart only that one; trap `SIGTERM`/`SIGINT` to set a shutdown flag and forward the signal to both children before exiting; never log environment variable values (depends on T008)
- [ ] T010 Set `Dockerfile`'s `ENTRYPOINT ["tini", "--", "/scripts/container-entrypoint.sh"]` and `EXPOSE 3000` only — no backend port exposed — in `Dockerfile` (depends on T008, T009)

**Checkpoint**: A container can be built, started, and stopped cleanly, with in-place crash-restart already wired in — user story work can now begin

---

## Phase 3: User Story 1 - Build and run the whole app as one container (Priority: P1) 🎯 MVP

**Goal**: An operator can build a single image and run it, reaching the full app (sign in, view/edit profile) through the one exposed port, and stop it cleanly

**Independent Test**: `docker build` + `docker run` from a clean checkout; confirm the sign-in and profile flows work through `http://localhost:3000`; confirm clean shutdown

### Implementation for User Story 1

- [ ] T011 [US1] Document and wire required runtime environment variables — backend (`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_JWT_SECRET`, `DATABASE_URL`) and frontend (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_API_URL`, `NEXT_SERVER_API_URL`) — confirming none have values baked into `Dockerfile` (only `ENV` declarations with no secret defaults, if any)
- [ ] T012 [US1] Validate `quickstart.md` Scenario 1: build the image, run a container with required env vars supplied via `-e`, sign in / view / edit a profile through `http://localhost:3000`, stop the container, and confirm no orphaned processes remain (`docker ps`, `docker top`)
- [ ] T013 [US1] Validate `quickstart.md` Scenario 2: confirm `curl http://localhost:8000/...` fails from outside the container and `docker port <container>` shows exactly one mapped port
- [ ] T014 [US1] Validate `quickstart.md` Scenario 4: `docker history --no-trunc` on the built image shows zero secret values in any layer
- [ ] T015 [US1] Validate `quickstart.md` Scenario 5: confirm the running container's process user is non-root via `docker run --rm <image> sh -c "whoami"`

**Checkpoint**: User Story 1 is fully functional and independently testable — this is the deployable MVP

---

## Phase 4: User Story 2 - Know when the running container is healthy (Priority: P2)

**Goal**: The container reports an accurate combined health status, based only on the frontend and backend processes themselves

**Independent Test**: `quickstart.md` Scenario 3 — health transitions to healthy within 60s, flips to unhealthy when either process is killed, and recovers via in-place restart without the container itself restarting

### Implementation for User Story 2

- [ ] T016 [P] [US2] Add an unauthenticated `GET /health` route per `contracts/healthcheck.md` in `backend/app/routes/health.py` — minimal JSON response (e.g. `{"status": "ok"}`), no database or external-service calls
- [ ] T017 [US2] Register the new health router in `backend/app/main.py` (depends on T016)
- [ ] T018 [US2] Implement `scripts/container-healthcheck.sh` per `contracts/healthcheck.md`: `curl -f http://127.0.0.1:8000/health` and `curl -f http://127.0.0.1:3000/`, exit 0 only if both succeed, exit 1 otherwise — no Supabase or other external check
- [ ] T019 [US2] Add a `HEALTHCHECK` instruction to `Dockerfile` invoking `scripts/container-healthcheck.sh`, with `--start-period` and `--interval` values consistent with SC-003 (healthy within 60s under normal conditions) (depends on T017, T018)
- [ ] T020 [US2] Validate `quickstart.md` Scenario 3: confirm health reports healthy within 60s of start; kill the backend process inside the running container and confirm health flips to unhealthy then back to healthy without the container restarting (`docker inspect` `StartedAt` unchanged); repeat for the frontend process

**Checkpoint**: User Stories 1 AND 2 both work independently — the deployment is now observable

---

## Phase 5: User Story 3 - Follow a runbook to deploy (Priority: P3)

**Goal**: An operator unfamiliar with the project can build, run, and deploy the image using only written documentation

**Independent Test**: `quickstart.md` Scenario 6 — hand `docs/docker.md` to someone unfamiliar with the setup and confirm they succeed using only the written steps

### Implementation for User Story 3

- [ ] T021 [P] [US3] Write `docs/docker.md` § Build: exact `docker build` command and expected output
- [ ] T022 [US3] Write `docs/docker.md` § Run Locally: exact `docker run` command with every required env var listed and explained, referencing FR-005 (secrets supplied at runtime only, never baked into the image)
- [ ] T023 [US3] Write `docs/docker.md` § Healthcheck & Restart Behavior: what "healthy" means (process liveness only, no Supabase check) and how crash-restart works, referencing `contracts/healthcheck.md` and `contracts/entrypoint.md`
- [ ] T024 [US3] Write `docs/docker.md` § Deploy to Bunny Magic Container: platform-specific deployment steps, including the single-port and runtime-configuration/secrets mechanism
- [ ] T025 [US3] Write `docs/docker.md` § Troubleshooting: common failure modes (missing env var → unhealthy container, port conflicts, stale build cache)
- [ ] T026 [US3] Validate `quickstart.md` Scenario 6: have someone unfamiliar with this feature follow `docs/docker.md` alone from a clean checkout and confirm they reach a running, healthy container

**Checkpoint**: All user stories independently functional — feature complete

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verification that spans all user stories

- [ ] T027 [P] Run the full `quickstart.md` validation (all 6 scenarios) end-to-end after all stories are complete
- [ ] T028 [P] Re-verify constitution Security Rules compliance: confirm `scripts/container-entrypoint.sh` and `scripts/container-healthcheck.sh` never log environment variable values
- [ ] T029 Verify reproducible builds per FR-009: rebuild the image twice from the same commit and confirm identical base image digests (no floating tags picked up a newer version)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - US1 has no dependency on US2/US3
  - US2 depends on the entrypoint/Dockerfile from Foundational, not on US1's validation tasks
  - US3's documentation describes behavior built in Foundational + US1 + US2, so it is easiest to write last, but does not technically require US1/US2's tasks to be checked off first
- **Polish (Phase 6)**: Depends on all three user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational — no dependency on US2/US3
- **User Story 2 (P2)**: Can start after Foundational — adds the `/health` route and healthcheck script on top of the same Dockerfile; independently testable via Scenario 3 without needing US1's validation tasks done first
- **User Story 3 (P3)**: Can start after Foundational — documents the behavior from Foundational/US1/US2; in practice easiest to write once those exist, but each doc section only needs the corresponding behavior to exist, not the other stories' tasks checked off

### Within Each User Story

- Foundational build/entrypoint work before story-specific validation
- Story complete before moving to the next priority (recommended, not required — stories are independent)

### Parallel Opportunities

- T002, T003, T004 (Setup) can run in parallel — different files
- T007 (Foundational) can run in parallel with T006 — different Dockerfile stages, no shared state until T008 combines them
- T016 (US2) can start in parallel with US1's validation tasks (T012–T015) — different files, no shared dependency
- T021 (US3) can start as soon as Foundational's Dockerfile exists, in parallel with US1/US2 validation tasks

---

## Parallel Example: Setup Phase

```bash
Task: "Create scripts/container-entrypoint.sh placeholder"
Task: "Create scripts/container-healthcheck.sh placeholder"
Task: "Create docs/docker.md skeleton with section headings"
```

## Parallel Example: Foundational Phase

```bash
Task: "Author Dockerfile backend dependency stage (pinned python:3.11-slim, pip install)"
# ...while, in the same Dockerfile but a different stage block:
Task: "Author Dockerfile frontend build stage (pinned node:20-slim, npm ci && npm run build)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Run `quickstart.md` Scenarios 1, 2, 4, 5 independently
5. Deploy/demo if ready — a single running, reachable, non-root container with no baked secrets is a genuinely deployable artifact on its own

### Incremental Delivery

1. Complete Setup + Foundational → buildable, runnable, crash-resilient container substrate ready
2. Add User Story 1 → validate → this is the MVP
3. Add User Story 2 → validate (health status becomes trustworthy/observable)
4. Add User Story 3 → validate (deployment becomes repeatable by anyone, not just whoever built it)
5. Each story adds value without breaking the previous ones — all three build on the same Foundational Dockerfile/entrypoint

---

## Notes

- [P] tasks = different files (or clearly separated concerns within `Dockerfile`), no dependencies
- [Story] label maps task to specific user story for traceability
- No automated test suite is introduced — every story's validation task runs the corresponding `quickstart.md` scenario directly against a real build
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently
- Avoid: vague tasks, same-file conflicts (all three `Dockerfile` stages are additive within Foundational, not left to be edited freely across later stories)
