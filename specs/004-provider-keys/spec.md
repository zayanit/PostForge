# Feature Specification: Provider Keys

**Feature Branch**: `004-provider-keys`

**Created**: 2026-07-26

**Status**: Draft

**Input**: User description: "Read docs/implementation-plan.md and create a specification for Phase 4: Provider Keys in a new branch"

## Clarifications

### Session 2026-07-26

- Q: When an active key is explicitly rejected as invalid during validation, what happens to its active status? → A: Automatically deactivate the invalid key and activate no replacement.
- Q: Can a key already marked invalid be activated again? → A: Block activation until the key passes validation.
- Q: How should quota, rate-limit, permission, or provider-service errors affect key validity? → A: Treat them as temporary failures and preserve the prior status.
- Q: How should keys behave after key or brand cleanup only partially succeeds? → A: Show a cleanup-required state and block normal key operations until deletion cleanup is retried successfully.
- Q: How should overlapping provider status codes be classified as invalid credentials versus temporary failures? → A: Use provider-specific documented authentication-error mappings; unknown responses remain temporary.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Add and view provider keys (Priority: P1)

As a signed-in brand owner, I can add my own OpenAI or Gemini key to a brand and see a safe summary of configured keys, so that the brand is ready to use my provider account without exposing the credential.

**Why this priority**: The product uses a bring-your-own-key model. Securely configuring a key is the minimum capability required before any future image generation can use a provider.

**Independent Test**: Can be fully tested by adding one key for each supported provider to an owned brand, reopening the keys view, and confirming both safe summaries appear while no full key value is returned or displayed.

**Acceptance Scenarios**:

1. **Given** a signed-in user viewing a brand they own, **When** they add an OpenAI key with an optional label, **Then** the key is securely stored for that brand and the user sees only its provider, label, masked hint, status, and dates.
2. **Given** a signed-in user viewing a brand they own, **When** they add a Gemini key and choose to make it active, **Then** it appears as the active Gemini key for that brand.
3. **Given** a key has already been added, **When** the owner lists or revisits their configured keys, **Then** the original key value is never returned or displayed.
4. **Given** a user who does not own a brand, **When** they attempt to list or add keys for that brand, **Then** the request is refused with the same outcome as for a nonexistent brand.

---

### User Story 2 - Validate a provider key (Priority: P1)

As a brand owner, I can validate a configured key against its selected provider, so that I know whether the credential is usable before attempting image generation.

**Why this priority**: Saving a credential without confirming it works leaves users unable to distinguish a valid setup from a typo or revoked key. Validation completes the core setup loop.

**Independent Test**: Can be fully tested with valid and invalid keys for both supported providers, confirming that each result records when validation occurred and presents a safe, actionable status without revealing the key.

**Acceptance Scenarios**:

1. **Given** an unvalidated OpenAI key, **When** the owner validates it and the provider accepts it, **Then** the key is marked valid and the validation time is shown.
2. **Given** an unvalidated Gemini key, **When** the owner validates it and the provider rejects it as unauthorized, **Then** the key is marked invalid with a safe explanation and the validation time is shown.
3. **Given** an active key, **When** validation confirms it is invalid, **Then** the key becomes inactive and no replacement key is activated automatically.
4. **Given** a provider is temporarily unavailable, **When** the owner attempts validation, **Then** the user sees a temporary validation failure, the key is not incorrectly marked invalid, and its previously recorded validation status, time, error, and active state remain unchanged.
5. **Given** validation receives a quota, rate-limit, permission, or other non-authentication provider error, **When** the result is shown, **Then** it is treated as a temporary failure and all previously stored validation and active state remains unchanged.
6. **Given** a provider returns an error whose meaning is undocumented or ambiguous, **When** validation classifies it, **Then** it is treated as temporary rather than invalidating the key.
7. **Given** validation has not completed within 15 seconds, **When** the deadline is reached, **Then** the attempt ends as a temporary timeout without changing stored key state.
8. **Given** validation is already in progress for a key, **When** another validation is requested for the same key, **Then** the overlapping request receives a temporary already-in-progress outcome and cannot change key state.
9. **Given** a user does not own the key's brand, **When** they attempt to validate the key, **Then** the request is refused without revealing whether either the brand or key exists.

---

### User Story 3 - Choose the active key (Priority: P2)

As a brand owner with multiple saved keys for a provider, I can choose which one is active, so that future work uses the intended provider account while older keys remain available until I remove them.

**Why this priority**: Users need a safe rotation path, but they can complete initial provider setup with a single active key before this capability is available.

**Independent Test**: Can be fully tested by adding two keys for one provider, activating the second, and confirming exactly one key is active while the first remains stored and inactive.

**Acceptance Scenarios**:

1. **Given** a brand with one active and one inactive OpenAI key, **When** the owner activates the inactive key, **Then** it becomes active and the previously active OpenAI key becomes inactive as one indivisible change.
2. **Given** a brand has an active OpenAI key, **When** the owner activates a Gemini key, **Then** the OpenAI key remains active because active-key selection is independent for each provider.
3. **Given** two concurrent attempts to activate different keys for the same brand and provider, **When** both complete, **Then** the brand still has no more than one active key for that provider.
4. **Given** a key is marked invalid, **When** the owner attempts to activate it, **Then** activation is blocked until a later validation succeeds.
5. **Given** validation and activation occur concurrently for the same key, **When** the completed validation result is invalid, **Then** the key is inactive regardless of operation ordering.
6. **Given** a user does not own the key's brand, **When** they attempt to activate the key, **Then** the request is refused without changing any key status.

---

### User Story 4 - Delete provider keys (Priority: P2)

As a brand owner, I can permanently delete a provider key I no longer trust or use, so that the credential and its saved metadata are removed from PostForge.

**Why this priority**: Credential revocation and cleanup are essential for security and trust, though adding and validating the first key deliver the initial setup value.

**Independent Test**: Can be fully tested by deleting active and inactive keys and confirming both their secure secret values and visible records are gone, while keys belonging to other brands remain untouched.

**Acceptance Scenarios**:

1. **Given** an inactive key, **When** its brand owner deletes it, **Then** both the stored secret and its key record are permanently removed.
2. **Given** an active key, **When** its brand owner deletes it, **Then** it is permanently removed and no other key is activated automatically.
3. **Given** a key deletion cannot remove the stored secret, **When** the owner attempts deletion, **Then** the operation is not reported as successful and the key record is retained so cleanup can be retried.
4. **Given** a brand with configured provider keys, **When** the owner successfully deletes the brand, **Then** every provider secret and key record belonging to that brand is also permanently removed.
5. **Given** one or more provider secrets cannot be removed during brand deletion, **When** the owner attempts to delete the brand, **Then** deletion is not reported as successful, the brand and its provider-key records remain available for retry, and no secret is left without a record that identifies it for cleanup.
6. **Given** key or brand cleanup has partially succeeded, **When** the owner views provider keys, **Then** affected keys are shown as cleanup-required and inactive, normal key operations are unavailable, and deletion cleanup can be retried.
7. **Given** a user does not own the key's brand, **When** they attempt to delete the key, **Then** the request is refused and the key remains unchanged.

---

### Edge Cases

- What happens when a key value is empty, contains only whitespace, is shorter than five characters, or does not end in four letters, digits, underscores, or hyphens? The add attempt is rejected as an unsupported key format and no secret or key record is created.
- What happens when a label is longer than 100 characters? The add attempt is rejected with a clear validation message; labels remain optional.
- What happens when the optional label contains the submitted raw key? The add attempt is rejected so the credential cannot be copied into ordinary metadata and later exposed.
- What happens when a user adds another active key for the same brand and provider? The new key becomes active and the prior active key becomes inactive as one indivisible change; historical inactive keys remain available.
- What happens when a user adds a key but does not make it active? It remains safely stored and can be validated or activated later without changing the current active key.
- What happens when a key is deleted while it is the only active key for its provider? That provider has no active key afterward; the system does not choose a replacement on the user's behalf.
- What happens when a key identifier belongs to another brand or does not exist? Both cases produce the same not-found outcome, including when the caller owns one brand but references a key from another.
- What happens when a provider rejects validation because the key is invalid versus when validation cannot reach the provider? Invalid credentials update the key to invalid; temporary provider or network failures are shown for that attempt only and do not overwrite the stored validation status, time, or error. A never-validated key remains unvalidated.
- What happens when the provider rejects an active key as invalid? The key is deactivated as part of recording the invalid result, and no other key is activated automatically.
- What happens when an owner tries to reactivate a key still marked invalid? Activation is blocked until the same key completes a successful validation; unvalidated keys remain eligible for activation.
- What happens when a provider recognizes the request but returns a quota, rate-limit, permission, or service error? Because the response does not conclusively prove credential validity, it is treated as temporary and does not change stored validation or active state.
- What happens when a provider error is undocumented or could mean either invalid authentication or insufficient permission? The provider-specific documented mapping is authoritative; anything not explicitly identified as authentication rejection is temporary.
- What happens when two validations are requested for the same key at once? Only the first proceeds; overlapping requests receive a temporary already-in-progress outcome and cannot overwrite the first result.
- What happens if Vault creation or key-record creation fails? Both occur in one database transaction and roll back together. If the client cannot tell whether commit succeeded, retrying the same idempotency key returns the committed record or safely performs the operation once.
- What happens if Vault cleanup succeeds but key-record cleanup is interrupted? A retry treats an already-absent secret as successfully cleaned up and completes record removal without exposing the key.
- What happens when deletion of several Vault secrets during brand deletion succeeds only partially? The brand and all provider-key records remain; records for already-removed secrets are retained until a retry idempotently completes all cleanup, preventing any remaining secret from becoming untracked.
- What happens when key creation, activation, or validation races with key or brand deletion? Once cleanup starts, conflicting normal key operations are rejected or serialized behind cleanup so no new or changed secret can escape the cleanup set.
- What happens when a Storage upload/removal has an unknown terminal outcome after timeout or process failure? A durable cleanup-required asset operation blocks further asset mutation and brand deletion; elapsed time or temporary absence never clears it without definitive reconciliation.
- What happens when a replacement logo succeeds but deletion of the prior logo fails? The new logo remains referenced, while a durable cleanup-required asset operation retains the prior path and blocks further mutation/deletion until cleanup is confirmed.
- What happens before Brand Kit exists? Provider-key setup remains fully functional and has no dependency on brand-kit data; Brand Kit verification is phase-gated under Constitution v2.0.0.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow an authenticated user to list provider keys configured for a brand they own.
- **FR-002**: System MUST allow a brand owner to add a key for OpenAI or Gemini with an optional label of at most 100 characters and a choice of whether to make the key active. The label MUST be rejected if it contains the submitted raw key.
- **FR-003**: System MUST reject key values that are empty, whitespace-only, shorter than five characters, or whose final four characters contain anything other than letters, digits, underscores, or hyphens, without creating either a stored secret or a key record.
- **FR-004**: System MUST store each raw provider key only in Supabase Vault; the associated key record MUST reference it only by an opaque Vault secret identifier.
- **FR-005**: System MUST never return a raw provider key to any client after submission, include it in logs, or persist it in ordinary application records.
- **FR-006**: Client-facing normal-key responses MUST be limited to safe metadata: identifier, provider, optional label, masked hint, active status, validation status, last validation time, safe validation error (if any), cleanup state, and creation time. A cleanup reference MUST expose only its identifier, provider, optional label, masked hint, cleanup-required state, and creation time; unavailable normal-key fields MUST be omitted or null.
- **FR-007**: A client-facing key hint MUST contain the fixed mask `***` followed by exactly the final four characters of the submitted key and MUST disclose no other part of the credential.
- **FR-008**: System MUST support multiple saved keys per brand and provider while permitting no more than one active key for each brand-provider combination.
- **FR-009**: When an eligible key is made active, the system MUST deactivate any previously active key for the same brand and provider as one indivisible change. A key marked invalid MUST NOT be activated until a later validation succeeds, and no completed operation sequence may leave a known-invalid key active.
- **FR-010**: Activating a key for one provider MUST NOT change the active key for another provider.
- **FR-011**: System MUST allow a brand owner to validate a saved key against the corresponding provider using only that provider's official service.
- **FR-012**: Validation MUST use a separate documented authentication-error mapping for each provider. A credential acceptance MUST be classified as valid, and only an error explicitly documented by that provider as authentication rejection MUST be classified as invalid, recording the result and validation time without exposing sensitive provider details. If a key confirmed invalid is active, the same operation MUST deactivate it and MUST NOT activate a replacement.
- **FR-013**: Any validation result not covered by the provider's explicit acceptance or authentication-rejection mapping, including unknown, ambiguous, quota, rate-limit, permission, provider-service, timeout, and network errors, MUST be reported as temporary for that attempt and MUST NOT change the key's stored validation status, last validation time, last validation error, or active state; a key with no prior completed validation MUST remain unvalidated.
- **FR-014**: System MUST allow a brand owner to permanently delete an active or inactive provider key, removing both its secure secret and its key record.
- **FR-015**: Deleting an active key MUST leave that provider with no active key unless the owner explicitly activates another one; no replacement key may be selected automatically.
- **FR-016**: A key deletion MUST NOT be reported as successful unless the Vault secret, normal key record, and any associated cleanup reference are removed; if Vault cleanup fails, a durable key or cleanup reference MUST remain, and an already-absent Vault secret MUST be treated as cleaned up on retry.
- **FR-017**: Successfully deleting a brand MUST permanently remove its Storage assets, all provider-key Vault secrets, normal key records, cleanup references, and the brand row itself. If any Storage or Vault cleanup fails, the brand deletion MUST NOT be reported as successful, and the brand plus all key and cleanup references MUST remain so cleanup can be retried without leaving an untracked secret or asset.
- **FR-018**: System MUST verify brand ownership for every key list, add, activate, validate, and delete operation on the server side.
- **FR-019**: For every operation on a specific brand or key, the system MUST return the same not-found outcome when the resource does not exist and when it belongs to another user.
- **FR-020**: Provider-key operations MUST NOT require Brand Kit data. Brand-kit state verification is not applicable until that capability exists and only becomes mandatory for later behavior that reads or depends on it.
- **FR-021**: The provider-keys experience MUST group or filter keys by provider and clearly display active, inactive, unvalidated, valid, and invalid states.
- **FR-022**: System MUST NOT perform image generation as part of adding, activating, validating, listing, or deleting a provider key.
- **FR-023**: Every persisted normal key and cleanup reference MUST enforce owner-only access at the data layer through Row Level Security in addition to server-side ownership verification.
- **FR-024**: Automated integration checks MUST verify owner isolation for listing, adding, activating, validating, deleting, and retrying cleanup. Direct authenticated data access MUST expose only safe owner-scoped metadata, MUST hide internal Vault/lease fields, and MUST block insert, update, and delete attempts for both same-owner and cross-owner records.
- **FR-025**: Vault secret creation and its normal key record MUST commit atomically so no committed secret can exist without a durable brand-scoped reference; ambiguous commit outcomes MUST be reconciled through idempotent retry.
- **FR-026**: If key deletion, brand deletion, or compensating cleanup partially fails, every affected retained key or cleanup reference MUST enter a visible cleanup-required state and MUST be inactive.
- **FR-027**: Keys in cleanup-required state MUST remain listable to their owner, MUST allow deletion cleanup to be retried, and MUST reject activation, validation, and other normal key changes until cleanup succeeds. A brand with pending provider-key cleanup MUST reject creation of additional keys.
- **FR-028**: Key creation, activation, validation, logo upload/removal, individual key deletion, and brand deletion MUST be coordinated so a conflicting operation cannot add, activate, alter, omit, or recreate a key or Storage asset while cleanup for that key or brand is in progress.
- **FR-029**: Authenticated clients MUST be unable to read raw provider-key values directly from Vault, and automated integration checks MUST verify Vault isolation independently of client-facing key and cleanup-reference responses.
- **FR-030**: The validation endpoint MUST return a safe outcome or pre-validation error within 15 seconds of backend entry. Every request that successfully acquires a validation lease MUST produce a valid, invalid, or temporary-failure outcome within that deadline; reaching the provider deadline MUST produce a temporary timeout outcome.
- **FR-031**: At most one validation attempt may be in progress for a key. An overlapping request MUST receive a temporary already-in-progress outcome within the normal validation deadline and MUST NOT modify stored key state.
- **FR-032**: Adding a provider key MUST be idempotent under client retry so an ambiguous database commit cannot create duplicate Vault secrets or key records. Reusing an add idempotency key after its provider key was deleted MUST be rejected rather than recreating the credential.
- **FR-033**: Every external Storage mutation MUST retain a durable brand-scoped operation record until its remote outcome and all required old/new object cleanup are definitively known. Unknown or abandoned operations MUST block further asset mutation and brand deletion and MUST NOT expire based only on elapsed time or absence polling.

### Key Entities

- **Provider Key**: A brand-scoped record describing one OpenAI or Gemini credential without containing the raw key. Includes an opaque Vault secret reference, optional label, safe masked hint, active state, validation state and timestamp, safe validation error, cleanup state, and creation date. A cleanup-required key is always inactive and cannot return to normal use.
- **Secret Cleanup Reference**: A durable, brand-scoped reference retained only when a Vault secret could not be associated with a normal key record or fully removed. It contains no raw credential, is visible as cleanup-required, and exists solely to support safe deletion retry.
- **Brand**: The single-owner tenancy boundary to which every provider key belongs. A brand can have multiple historical keys but at most one active key per provider.
- **Provider**: One of the supported external image providers, OpenAI or Gemini. Active-key selection and validation status are tracked independently per provider.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A brand owner can add a provider key and see its safe summary in under 2 minutes, without the raw value appearing again after submission.
- **SC-002**: 100% of provider-key responses, cleanup-reference responses, user-visible screens, ordinary application records, and logs omit the raw key value; Supabase Vault is the sole permitted storage location for that value.
- **SC-003**: For both OpenAI and Gemini, when the official provider responds within 10 seconds, the user sees the corresponding valid, invalid, or temporary-failure outcome within 15 seconds of starting validation.
- **SC-004**: 100% of quota, rate-limit, permission, provider-service, timeout, and network validation failures preserve all stored validation and active state and clearly indicate that validation could not be completed.
- **SC-005**: After any sequence of additions and activations, every brand has at most one active key per provider, including under concurrent activation attempts.
- **SC-006**: 100% of unauthorized list, add, activate, validate, and delete attempts are blocked without revealing whether another user's brand or key exists.
- **SC-007**: 100% of successful key deletions remove both the secure secret and visible key record; deleting an active key never activates a replacement without an explicit owner action.
- **SC-008**: 100% of successful brand deletions remove every provider-key secret and record, every Storage asset, and the brand row itself.
- **SC-009**: Key management and validation complete successfully before Brand Kit exists, with no brand-kit record or answers required.
- **SC-010**: Direct data-layer isolation checks expose only safe metadata for the owner, expose no rows to non-owners, hide all Vault/lease fields, and block 100% of authenticated insert, update, and delete attempts regardless of ownership.
- **SC-011**: In 100% of injected partial-creation and partial-deletion failures, every remaining Vault secret retains a durable brand-scoped cleanup reference, no affected key remains active, normal key operations stay blocked until cleanup succeeds, and successful retry removes the secret plus all normal and cleanup-reference records.
- **SC-012**: Direct Vault isolation checks confirm that authenticated clients cannot retrieve raw provider-key values for either their own or another user's brand.
- **SC-013**: 100% of validation endpoint requests return a safe outcome or pre-validation error within 15 seconds; every request with an acquired lease returns valid, invalid, or temporary, and overlapping requests never overwrite the in-progress result.
- **SC-014**: Retrying an add-key request after any ambiguous response creates at most one Vault secret and one provider-key record.

## Assumptions

- Provider keys are user-supplied under the existing bring-your-own-key product model; PostForge does not issue, sell, or recover provider credentials.
- OpenAI and Gemini are the only providers in scope for this feature.
- Users may retain multiple inactive historical keys for rotation; usage limits and automatic pruning are out of scope.
- Validation confirms credential acceptance through a minimal server-side provider check and does not generate or store an image.
- Planning will select one official, non-generation validation operation per provider whose documented response semantics support the provider-specific authentication-error mappings required above.
- Provider-specific quota, billing, model access, or organization-policy limitations may still affect later generation even when a credential validates successfully; validation is not a guarantee of all future provider operations.
- Raw key editing or reveal is out of scope. To change a credential, the user adds a new key and deletes the old one.
- Key labels are optional organizational metadata and need not be unique.
- Existing authentication, brand ownership, and safe structured-logging behavior are reused and extended rather than redefined. Existing brand deletion must be extended so it cannot report success while any provider-key Vault secret or record remains.
- Supabase Vault and Row Level Security are explicit constitutional constraints for this feature, not interchangeable implementation choices.
- No automatic key rotation, scheduled revalidation, expiration reminders, or provider-account management is included in this phase.
