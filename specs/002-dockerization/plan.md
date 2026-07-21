# Implementation Plan: Dockerization

**Branch**: `002-dockerization` | **Date**: 2026-07-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-dockerization/spec.md`

## Summary

Package the existing Next.js 14 frontend and FastAPI backend into a single container
image deployable to Bunny Magic Container, per `docs/implementation-plan.md` § Phase 2 /
§ Dockerization. A multi-stage `Dockerfile` builds both apps into a slim runtime image
running as a non-root user; a bash entrypoint starts both processes, forwards signals for
clean shutdown, and independently restarts either process if it crashes (per spec
clarification) without restarting the whole container. Health is reported via a single
combined healthcheck that requires both processes to be responding — deliberately
excluding external Supabase reachability (per spec clarification) so the container's own
health signal isn't coupled to a downstream dependency's uptime. No new backend business
logic beyond adding the already-planned `GET /health` endpoint (defined in
`docs/implementation-plan.md` but not yet implemented).

## Technical Context

**Language/Version**: Bash (POSIX-compatible, requires `wait -n`) for the container
entrypoint/healthcheck scripts; existing Python 3.11 (FastAPI backend) and Node.js 20 LTS
(Next.js 14 frontend) runtimes, unchanged by this feature

**Primary Dependencies**: Docker multi-stage build (`node:20-slim` build stage for the
frontend, `python:3.11-slim` stage for backend dependencies, combined into one
`python:3.11-slim` runtime stage with Node.js 20 installed for `next start`); `tini` as
PID 1 for correct signal forwarding and zombie reaping around the custom entrypoint
supervisor

**Storage**: N/A — this feature only packages application code; Supabase (Auth, DB, Vault,
Storage) continues to run externally, unchanged

**Testing**: Manual/scripted validation via `docker build` + `docker run` against the
quickstart guide (build succeeds, both processes serve traffic through the one exposed
port, healthcheck transitions correctly, restart-in-place verified by killing one process);
no new automated test framework introduced — this is infrastructure, not application logic

**Target Platform**: Linux container image (`linux/amd64`), deployed as a single Bunny
Magic Container instance per the existing architecture decision

**Project Type**: Infrastructure/packaging — adds root-level `Dockerfile`,
`.dockerignore`, `scripts/container-entrypoint.sh`, `scripts/container-healthcheck.sh`,
and `docs/docker.md`; no new application source trees under `frontend/` or `backend/`
beyond the one new `GET /health` route needed to make the healthcheck possible

**Performance Goals**: SC-003 — combined health status reports healthy within 60 seconds
of container start under normal conditions; no new throughput targets (packaging only,
does not change request-handling code paths)

**Constraints**: Exactly one publicly reachable port (frontend); backend listens on
`127.0.0.1` only inside the container (FR-002); no secrets baked into image layers
(FR-005, SC-005); non-root runtime user (FR-006); pinned base image tags, no floating
`latest` (FR-009); a crashed frontend or backend process is restarted individually by the
entrypoint, not by restarting the container (FR-003a, per clarification)

**Scale/Scope**: Single container instance for MVP; no multi-container orchestration or
autoscaling in scope (per spec Assumptions)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Applicability to this feature | Status |
|---|---|---|
| I. Product Truth (brand-based tenancy, BYOK, image generation) | Not applicable — this feature packages existing code for deployment; it introduces no brand, key, or generation concepts | Pass (N/A) |
| II. Non-Negotiables (brand isolation, hard delete, key secrecy, official endpoints, PNG-only) | Not applicable — no data model or provider calls are touched by this feature | Pass (N/A) |
| III. Tech Constraints (Next.js 14, FastAPI, Supabase, **Bunny Magic Containers**) | Directly applicable — this feature exists specifically to satisfy the Bunny Magic Container hosting constraint; frontend/backend stack is unchanged | Pass |
| IV. Data Rules (generation/brand-kit/provider-key storage rules) | Not applicable — no persistence changes | Pass (N/A) |
| V. UX Rules (prompt-first, brand-kit interview, presets, history) | Not applicable — no product UX changes | Pass (N/A) |
| VI. Security Rules (RLS on all tables; server-side verification; no secrets/PII in logs) | Applicable to the "no secrets in logs" clause — the entrypoint and healthcheck scripts MUST NOT log environment variable values; FR-005/SC-005 (no baked secrets) is this feature's equivalent of Key Secrecy for the image build itself | Pass, enforced in design (see contracts/) |
| VII. Definition of Done (brand-kit/provider/hard-delete checks) | Not applicable — this feature has no brand, provider, or generation surface to verify against | Pass (N/A) |

No violations requiring justification — every non-applicable principle is non-applicable
because this feature is infrastructure packaging with no data model or product-capability
surface, not because a rule was bypassed. No Complexity Tracking entries needed.

**Post-Phase 1 re-check**: Design adds one new backend route (`GET /health`, no auth,
per `docs/implementation-plan.md`'s already-planned API surface) and two new scripts
(entrypoint, healthcheck). Neither introduces secrets into logs or the image, and neither
touches brand/generation data. No new violations introduced.

## Project Structure

### Documentation (this feature)

```text
specs/002-dockerization/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (N/A — no data entities; documents why)
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── healthcheck.md
│   └── entrypoint.md
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── main.py                      # Add: GET /health (no auth), per docs/implementation-plan.md
│   └── routes/
│       └── health.py                # New: dedicated health route, separate from auth-gated routes

Dockerfile                            # New: multi-stage build (frontend build, backend deps, runtime)
.dockerignore                         # New: excludes node_modules, .venv, .env*, .git, test artifacts
scripts/
├── container-entrypoint.sh           # New: starts both processes, supervises + restarts crashed one, forwards signals
└── container-healthcheck.sh          # New: combined healthcheck, curls both processes' health surfaces
docs/
└── docker.md                         # New: build/run/deploy runbook (referenced by FR-008)
```

**Structure Decision**: This is an infrastructure feature — it adds root-level packaging
artifacts (`Dockerfile`, `.dockerignore`, `scripts/`, `docs/docker.md`) rather than a new
`frontend/`/`backend/` subtree, matching `docs/implementation-plan.md` § Files to Create
(Root). The only application code change is one new backend route (`GET /health`) needed
because the combined healthcheck (User Story 2) has nothing to poll on the backend side
today — `main.py` currently only exposes `GET /` (see `backend/app/main.py:105-107`),
not the `/health` path already documented in `docs/implementation-plan.md`'s API surface.

## Complexity Tracking

*No entries — no Constitution Check violations.*
