# Feature Specification: Image Generation (OpenAI-first release)

**Feature Branch**: `007-image-generation`

**Created**: 2026-10-27

**Status**: Implemented (specification written retroactively; see note)

**Input**: `docs/implementation-plan.md` Phase 6 (Generation) and Phase 7 (History), narrowed to an OpenAI-first release.

> **Process note.** This feature was implemented in commit `64d2a48` before any
> spec-kit artifact other than `tasks.md` existed. This file and the other artifacts
> in this directory were written afterwards to record the requirements and design
> as built, and the review fixes made in PR #24. They describe behavior verified by
> the test suites; they are not a forward-looking design. Future generation work
> (Gemini, logo processing) must start from a new spec through `/speckit-specify`.

## Clarifications

### Scope decisions recorded at implementation (2026-10-27)

- Q: Which providers ship in this release? → A: OpenAI only (`gpt-image-2`, medium quality, one image per request). Gemini generation is deferred; existing Gemini key management is unchanged.
- Q: Is logo watermarking included? → A: No. Logo processing (roadmap task 6.6 and logo modes 6.12) is deferred.
- Q: Is generation synchronous? → A: No. Submission persists a job and returns 202; a separate supervised worker processes it. Users may leave the page.
- Q: Are failed or interrupted provider calls retried automatically? → A: No. Provider calls are paid on the user's own key, so a retry is always an explicit user action.
- Q: Are generated images public? → A: No. They live in a private bucket and are served through five-minute signed URLs issued after an ownership check.
- Q: Can a user generate with an incomplete Brand Kit? → A: Yes. Empty, partial, and complete kits are all snapshotted into the job's context.

## User Scenarios & Testing

### User Story 1 - Generate a brand-aware image (Priority: P1)

A signed-in brand owner with an active OpenAI key writes a prompt, picks a platform preset, and receives a PNG at the preset's exact dimensions that reflects the brand's saved context.

**Why this priority**: Image generation is the product's sole capability (Constitution I).

**Independent Test**: With an active OpenAI key, submit a prompt for each preset and verify each result is a PNG of exactly the preset's width and height.

**Acceptance Scenarios**:

1. **Given** an owner with an active OpenAI key, **When** they submit a 3–4,000 character prompt and a preset, **Then** a job is created and returned with status `pending` (HTTP 202).
2. **Given** a pending job, **When** the worker completes it, **Then** its status becomes `succeeded` and it exposes a PNG of exactly the preset dimensions.
3. **Given** no preset is chosen, **When** the owner tries to submit, **Then** submission is blocked (no default preset).
4. **Given** the brand has no active, usable OpenAI key, **When** the owner submits, **Then** submission fails with `OPENAI_KEY_REQUIRED` and a link to provider settings.
5. **Given** an empty, partial, or complete Brand Kit, **When** a job is submitted, **Then** the brand name and whatever kit answers exist are snapshotted with the job; later kit edits do not change it.

### User Story 2 - Durable jobs that survive leaving the page and restarts (Priority: P1)

Generation continues if the user navigates away, reloads, or the worker restarts, and a paid provider call is never repeated automatically.

**Why this priority**: Calls take up to three minutes and are billed to the user's key.

**Independent Test**: Submit, close the tab, and confirm the result appears in history. Kill the worker mid-job and confirm the job ends in a definite state without a second provider call.

**Acceptance Scenarios**:

1. **Given** a submitted job, **When** the user leaves and returns, **Then** the job's current status and result are shown.
2. **Given** a network failure during submission, **When** the user submits the same input again, **Then** the same idempotency key is reused and no duplicate job is created.
3. **Given** a worker that stopped mid-job, **When** its lease expires, **Then** another worker reconciles the job: a stored image is published, otherwise the job fails with `GENERATION_INTERRUPTED` without calling the provider again.
4. **Given** a normal container stop, **When** a job is in progress, **Then** the worker finishes it before exiting, provided the stop timeout allows (see plan).

### User Story 3 - Private history, preview, and download (Priority: P1)

A brand owner views their brand's generations newest-first, filters by status, previews and downloads PNGs, and nobody else can see them.

**Why this priority**: History is first-class (Constitution V) and brand isolation is non-negotiable (Constitution II).

**Independent Test**: As two users, generate under each brand and verify neither can list, read, sign, or delete the other's generations.

**Acceptance Scenarios**:

1. **Given** generations exist, **When** the owner opens history, **Then** they are listed newest-first, 20 per page, with status, preset, dimensions, prompt, and time.
2. **Given** a status filter, **When** applied, **Then** only matching generations are listed.
3. **Given** a succeeded generation, **When** shown or downloaded, **Then** the image is served via a freshly signed URL that expires after five minutes; the UI renews links before they expire.
4. **Given** another user's brand or generation ID, **When** requested, **Then** a generic not-found response is returned with no data.

### User Story 4 - Permanent deletion (Priority: P2)

An owner permanently deletes a generation (its PNG and record), and deleting a brand removes all of its generated images.

**Why this priority**: Hard delete is non-negotiable (Constitution II).

**Independent Test**: Delete a generation and verify the storage object and database row are both gone; delete a brand and verify its generation prefix is empty.

**Acceptance Scenarios**:

1. **Given** a pending, succeeded, or failed generation, **When** the owner confirms deletion, **Then** the PNG (if any) and the record are physically removed.
2. **Given** a processing generation, **When** deletion is requested, **Then** it is refused with `GENERATION_PROCESSING`.
3. **Given** storage deletion fails, **When** the request completes, **Then** the record remains marked `cleanup_required` and the owner can retry from history.
4. **Given** a brand with generations, **When** the brand is deleted, **Then** its generated images are removed along with logos, keys, and rows.

### Edge Cases

- The same idempotency key is reused with different input (→ 409 `IDEMPOTENCY_CONFLICT`).
- The OpenAI key is revoked, deactivated, or rejected between submission and processing.
- OpenAI times out, rate-limits, rejects the prompt, or returns a malformed or oversized image.
- An upload's outcome is unknown (timeout after the request was sent).
- The brand is deleted while a job is pending, processing, or uploading.
- A user deletes one image while the worker is saving another for the same brand.
- A worker loses its lease while still running; it must not publish.
- Wide or tall presets (e.g. LinkedIn Banner, 4:1) where most of the provider canvas is cropped away.
- The database is unavailable while the worker is idle or mid-job.
- Network failure on submission, polling, or download.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST accept a generation request with a trimmed prompt of 3–4,000 characters, one of the 13 supported platform presets, and an `Idempotency-Key` UUID; provider/model, if supplied, MUST be `openai`/`gpt-image-2`; unknown fields MUST be rejected.
- **FR-002**: The system MUST persist the job and return HTTP 202 before any provider call. Repeating a key with identical input MUST return the existing job; with different input MUST return 409.
- **FR-003**: The system MUST snapshot the brand name and current Brand Kit answers (any completeness) and the selected key's opaque ID at submission.
- **FR-004**: A worker MUST claim jobs atomically, hold a renewable five-minute lease identified by a token, and MUST NOT publish results after losing its lease or after the brand is fenced for deletion.
- **FR-005**: Claims MUST favor the brand whose oldest claimable job has waited longest, so one brand's backlog cannot starve others.
- **FR-006**: The worker MUST call only the official OpenAI Images endpoint, from the server, with the decrypted key never logged or returned.
- **FR-007**: The prompt sent to the provider MUST include the brand context, the user's prompt, and a composition note stating the final size and the share of the canvas that survives the crop.
- **FR-008**: Output MUST be a PNG of exactly the preset's dimensions, produced by center-crop and resize.
- **FR-009**: Provider calls MUST NOT be retried automatically; failures MUST be recorded with one of the defined error codes.
- **FR-010**: After a worker stops mid-job, recovery MUST publish an already-stored image or mark the job `GENERATION_INTERRUPTED`, and MUST NOT call the provider.
- **FR-011**: Images MUST be stored privately at `brands/{brandId}/generations/{generationId}.png` and served only through five-minute signed URLs issued after an ownership check.
- **FR-012**: History MUST be brand-scoped, newest-first, paginated (default 20, max 100), and filterable by status and provider.
- **FR-013**: Deletion MUST physically remove the stored PNG and the row; processing jobs MUST NOT be deletable; storage failures MUST leave a retryable `cleanup_required` record.
- **FR-014**: Brand deletion MUST remove generated images and MUST wait out any upload whose outcome is uncertain.
- **FR-015**: Publication and deletion for a brand MUST be serialized; when the lock is busy, the worker MUST wait (bounded) rather than discard a completed image, and a brand deletion request MUST receive a retryable busy response without being fenced.
- **FR-016**: Logs MUST contain only allowlisted safe fields (event, IDs, outcome, error code, exception class name, durations), never messages or exception text.
- **FR-017**: Container health MUST reflect worker liveness without depending on database or Supabase availability.
- **FR-018**: The UI MUST NOT show raw browser network errors; a failed submission MUST tell the user that retrying is safe.

### Key Entities

- **Generation**: one brand-scoped job and its result. See `data-model.md`.
- **Generation asset**: the private PNG object at a deterministic path derived from the generation's brand and ID.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every one of the 13 presets yields a PNG of exactly its dimensions (automated, per preset).
- **SC-002**: Concurrent duplicate submissions with one key create exactly one job (integration test).
- **SC-003**: No test scenario (restart, lease loss, brand fencing, uncertain upload) produces a second provider call or a publication by a stale worker.
- **SC-004**: Cross-owner requests for list, detail, sign, and delete disclose no data (contract and RLS tests).
- **SC-005**: Deletion leaves no stored object and no row for the generation (integration test against isolated PostgreSQL; real Storage is a release gate).
- **SC-006**: While a history page has in-progress items, its frequent (2-second) status polls fetch only those items and never re-request the list or re-sign images. Full-list refreshes happen only to renew image links (every four minutes), once when an in-progress item finishes, and after a deletion.

## Assumptions

- Users bring their own OpenAI key; there is no application-wide key and no billing.
- One worker process per container; horizontal scaling adds containers.
- OpenAI returns square, landscape, or portrait canvases only; exact preset sizes come from post-processing.
- Gemini generation, logo watermarking, batch generation, cancellation, and automatic retries are out of scope.
