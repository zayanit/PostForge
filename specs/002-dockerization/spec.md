# Feature Specification: Dockerization

**Feature Branch**: `002-dockerization`

**Created**: 2026-07-22

**Status**: Draft

**Input**: User description: "Read @docs/implementation-plan.md and create a specification for phase 2 Dockerization"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Build and run the whole app as one container (Priority: P1)

As the operator responsible for deploying PostForge, I can build a single container image that packages both the frontend and the backend, and run it as one unit, so that deploying the product doesn't require coordinating two separate services or hosts.

**Why this priority**: Without a single deployable image, there is no way to ship the product to the target hosting platform (a single-image container host). This is the foundation every later deployment depends on.

**Independent Test**: Can be fully tested by building the image from a clean checkout and starting a container from it, then confirming both the sign-in flow and profile page work end-to-end through the single exposed address — delivers a genuinely deployable artifact on its own.

**Acceptance Scenarios**:

1. **Given** a clean checkout of the repository, **When** the operator builds the container image, **Then** the build completes successfully and produces one image containing both the frontend and backend.
2. **Given** a built image, **When** the operator starts a container from it with the required configuration supplied, **Then** a user can sign in, view, and edit their profile through the single exposed address, exactly as they could with the two services run separately in local development.
3. **Given** a running container, **When** the operator stops it, **Then** both the frontend and backend shut down without leaving orphaned processes.

---

### User Story 2 - Know when the running container is healthy (Priority: P2)

As the operator, I can check the container's health status and get an accurate answer, so that I can detect a broken deployment automatically instead of finding out from a user complaint.

**Why this priority**: A single-image deployment hides two independent processes behind one container; without a combined health signal, the hosting platform (or the operator) cannot tell whether the app is actually usable versus just "the container is running."

**Independent Test**: Can be fully tested by starting the container, polling its health status until it reports healthy, then stopping the backend process inside the container and confirming the health status flips to unhealthy — delivers reliable failure detection on its own.

**Acceptance Scenarios**:

1. **Given** a freshly started container, **When** both the frontend and backend have finished starting, **Then** the container's health status reports healthy.
2. **Given** a running, healthy container, **When** the backend process stops responding, **Then** the health status reports unhealthy within one check interval.
3. **Given** a running, healthy container, **When** the frontend process stops responding, **Then** the health status reports unhealthy within one check interval.

---

### User Story 3 - Follow a runbook to deploy (Priority: P3)

As the operator, I can follow written documentation to build, run, and deploy the container image to the target hosting platform, so that deployment doesn't depend on undocumented tribal knowledge.

**Why this priority**: Valuable once the image itself works (P1) and is observable (P2); documentation multiplies the value of both by making the process repeatable by anyone, not just whoever built it.

**Independent Test**: Can be fully tested by handing the documentation to someone unfamiliar with the setup and confirming they can build, run, and deploy the image using only the written steps.

**Acceptance Scenarios**:

1. **Given** the written deployment documentation and a clean checkout, **When** an operator unfamiliar with the project follows the steps, **Then** they successfully produce a running container without needing outside help.
2. **Given** the documentation, **When** an operator looks for how secrets/configuration are supplied to the container, **Then** the documentation clearly explains the mechanism without instructing them to bake secrets into the image.

---

### Edge Cases

- What happens if the frontend process crashes but the backend keeps running (or vice versa)? The container's health status must reflect the failure, and the container should not continue reporting itself as fully healthy with only one process alive.
- What happens when the operator stops the container while it's mid-startup (before both processes are ready)? Shutdown must still be clean, with no leftover processes.
- What happens if someone tries to reach the backend directly instead of through the frontend? The backend must not be reachable from outside the container; only the frontend's single public port is exposed.
- What happens if required runtime configuration (e.g., credentials the app needs to reach its external services) is missing when the container starts? The container should fail to become healthy rather than silently running in a broken state.
- What happens on a rebuild — does the build produce the same result given the same source and pinned versions? The build must not silently pick up a newer, unpinned version of a base image or dependency.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a single container image that packages and runs both the frontend and the backend together.
- **FR-002**: The system MUST expose exactly one publicly reachable network address (the frontend); the backend MUST NOT be reachable from outside the container.
- **FR-003**: The system MUST start both the frontend and backend from a single entrypoint, and MUST stop both cleanly (no orphaned processes) when the container receives a stop signal.
- **FR-004**: The system MUST expose a combined health status that reflects the readiness of both the frontend and the backend — the status MUST NOT report healthy unless both are actually able to serve requests.
- **FR-005**: The system MUST NOT include secret values (API keys, credentials, tokens) inside the built image; all secrets MUST be supplied at container start time through runtime configuration, not baked in at build time.
- **FR-006**: The system MUST run the application processes inside the container as a non-privileged (non-root) user.
- **FR-007**: The build process MUST exclude files unnecessary to running the app (local dependency caches, local env files, build artifacts, version control metadata) from what gets sent to the image build.
- **FR-008**: The system MUST be accompanied by documentation that explains how to build the image, run it locally, and deploy it to the target hosting platform, including how runtime configuration and secrets are supplied.
- **FR-009**: The container build MUST be reproducible — base images and dependencies MUST be pinned to specific versions rather than floating tags, so the same source produces an equivalent image on every build.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator following the documentation can go from a clean checkout to a running, fully-functional local container in under 10 minutes.
- **SC-002**: Scanning the running container from outside shows exactly one reachable network address; the backend is not independently reachable.
- **SC-003**: The container's health status reports healthy within 60 seconds of starting under normal conditions, and flips to unhealthy within one check interval whenever either the frontend or backend stops responding.
- **SC-004**: 100% of container stop/restart cycles result in both processes stopping and restarting cleanly, with no manual cleanup required.
- **SC-005**: Inspecting the built image's contents and history reveals zero secret values.

## Assumptions

- The target hosting platform is a single-image container host (Bunny Magic Container, per the existing architecture decision); this feature covers packaging the app for that model, not multi-container orchestration or autoscaling.
- Supabase (Auth, Database, Storage, Vault) continues to run externally as a managed service; this feature only concerns packaging the frontend and backend application code, not containerizing Supabase itself.
- Local day-to-day development (running frontend/backend directly on the host) remains unchanged; this feature adds a deployable packaging path alongside it, not a replacement for local dev workflow.
- "Health" here means a liveness/readiness signal for both processes, not a full synthetic end-to-end transaction test.
- Runtime configuration (including secrets) is supplied via the hosting platform's environment/secret mechanism at container start; how the operator manages secrets outside the container (e.g., a secrets vault or host environment) is out of scope for this feature.
