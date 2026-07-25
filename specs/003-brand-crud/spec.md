# Feature Specification: Brand CRUD

**Feature Branch**: `003-brand-crud`

**Created**: 2026-07-25

**Status**: Draft

**Input**: User description: "Read docs/implementation-plan.md and create a specification for Phase 3: Brand CRUD"

## Clarifications

### Session 2026-07-25

- Q: What's the maximum allowed file size for a brand logo upload? → A: 5 MB.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create a brand (Priority: P1)

As a signed-in user, I can create a new brand by giving it a name, so that I have a place to organize all future content generation work under a distinct identity.

**Why this priority**: Nothing else in the product is possible without a brand — it's the foundational container every other capability (brand kit, provider keys, generation) attaches to. This is the true starting point of the product experience after signup.

**Independent Test**: Can be fully tested by signing in with a fresh account, creating a brand with a name, and confirming it now exists — delivers the minimum viable "I have a brand to work with" outcome on its own.

**Acceptance Scenarios**:

1. **Given** a signed-in user with no brands yet, **When** they create a brand named "Acme Coffee", **Then** the brand is created and immediately visible as theirs.
2. **Given** a signed-in user who already owns a brand named "Acme Coffee", **When** they try to create another brand named "acme coffee" (any capitalization), **Then** the system rejects it with a clear message and no duplicate is created.
3. **Given** a signed-in user, **When** they try to create a brand with an empty name or a name longer than the allowed limit, **Then** the system rejects it with a clear validation message and no brand is created.

---

### User Story 2 - View my brands (Priority: P1)

As a signed-in user, I can see a list of all the brands I own and open any one of them to view its details, so that I can find and switch between the brands I've created.

**Why this priority**: Equally foundational to creation — a user needs to confirm a brand was created and be able to navigate to it. Without this, brand creation delivers no visible value.

**Independent Test**: Can be fully tested by signing in as a user with zero, one, and several brands, and confirming the list (and each brand's detail view) shows exactly the right ones — delivers the ability to see and select among owned brands on its own.

**Acceptance Scenarios**:

1. **Given** a signed-in user with no brands, **When** they view their brand list, **Then** they see an empty state, not an error.
2. **Given** a signed-in user who owns three brands, **When** they view their brand list, **Then** they see exactly those three brands and no others.
3. **Given** a signed-in user, **When** they open one of their own brands, **Then** they see that brand's name, logo (if any), and creation date.
4. **Given** a signed-in user, **When** they try to open a brand ID that belongs to a different user (or doesn't exist at all), **Then** they see the same "not found" outcome in both cases — the system never reveals that a brand owned by someone else exists.

---

### User Story 3 - Add or remove a brand logo (Priority: P2)

As a signed-in user, I can upload a logo image for one of my brands and remove it later, so that my brand has a recognizable visual identity I can reuse in generated content.

**Why this priority**: Meaningfully improves a brand's identity and sets up later logo-in-generation features, but a brand is fully usable without a logo — this isn't required for the MVP loop of creating and viewing brands.

**Independent Test**: Can be fully tested by uploading an image to an existing brand, confirming it displays as that brand's logo, then removing it and confirming the brand reverts to having no logo — delivers brand personalization on its own.

**Acceptance Scenarios**:

1. **Given** a brand with no logo, **When** the owner uploads a valid image, **Then** the brand now shows that image as its logo.
2. **Given** a brand that already has a logo, **When** the owner uploads a new image, **Then** the new image replaces the old one — only one logo exists for the brand at a time.
3. **Given** a brand with a logo, **When** the owner removes it, **Then** the brand shows no logo afterward.
4. **Given** a signed-in user, **When** they try to upload a file that isn't a supported image type, or one that's too large, **Then** the upload is rejected with a clear message and any existing logo is left unchanged.

---

### User Story 4 - Delete a brand (Priority: P3)

As a signed-in user, I can permanently delete a brand I no longer need, so that my brand list only contains things I'm actively using.

**Why this priority**: Important for a complete, trustworthy CRUD experience, but the least urgent of the four — a user can fully use the product by creating, viewing, and personalizing brands without ever needing to delete one.

**Independent Test**: Can be fully tested by creating a brand (with a logo), deleting it through the confirmation flow, and confirming both the brand and its logo are gone — delivers permanent cleanup on its own.

**Acceptance Scenarios**:

1. **Given** a brand the user owns, **When** they choose to delete it and correctly complete the confirmation step, **Then** the brand and its logo are permanently removed and the brand no longer appears anywhere for that user.
2. **Given** a brand the user owns, **When** they start the delete flow but fail to complete the confirmation correctly (e.g., type the wrong name), **Then** the brand is not deleted and remains exactly as it was.
3. **Given** a brand with no logo, **When** the owner deletes it, **Then** deletion still completes successfully.
4. **Given** a signed-in user, **When** they attempt to delete a brand that belongs to a different user, **Then** the deletion is refused and that brand is unaffected.

---

### Edge Cases

- What happens when a user submits a brand name that's empty, only whitespace, or exceeds the length limit? Rejected with a validation message; no brand is created or changed.
- What happens when a user tries to create a brand whose name matches an existing brand of theirs, ignoring case and surrounding whitespace? Rejected as a duplicate; no new brand is created.
- What happens when a user references a brand ID that belongs to another user, or doesn't exist at all, for any operation (view, upload logo, delete, etc.)? Both cases produce the identical "not found" outcome — brand ownership is never revealed or implied by the response.
- What happens when a logo removal or brand deletion's storage cleanup fails after the record itself is already gone (or vice versa)? The system prioritizes completing the deletion the user asked for and does not leave an orphaned, inaccessible brand behind; a storage cleanup failure is logged for operator follow-up rather than blocking the user-visible deletion.
- What happens when a user uploads a non-image file, a corrupted image, or an image larger than the allowed size as a logo? Rejected with a clear message; the brand's existing logo (if any) is untouched.
- What happens when a user tries to remove a brand's logo when the brand doesn't currently have one? Treated as a successful no-op — the brand still has no logo afterward, and no error is shown.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow an authenticated user to create a brand by providing a name.
- **FR-002**: System MUST require a brand name to be between 2 and 120 characters after trimming surrounding whitespace.
- **FR-003**: System MUST prevent a user from owning two brands with the same name, comparing names without regard to case or surrounding whitespace.
- **FR-004**: System MUST allow a user to view the list of all brands they own.
- **FR-005**: System MUST allow a user to view the details of a single brand they own, including its name, logo (if any), and creation date.
- **FR-006**: System MUST prevent a user from viewing, uploading/removing the logo of, or deleting a brand they do not own.
- **FR-007**: System MUST respond identically whether a requested brand ID belongs to another user or does not exist at all — brand existence MUST NOT be revealed to non-owners.
- **FR-008**: System MUST allow a user to upload a logo image for a brand they own.
- **FR-009**: System MUST allow a user to remove a brand's logo; if the brand has no logo at the time, this MUST succeed as a no-op rather than fail.
- **FR-010**: System MUST ensure a brand has at most one logo at a time — uploading a new logo replaces any previous one.
- **FR-011**: System MUST reject a logo upload that is not a supported image format or exceeds 5 MB, leaving any existing logo unchanged.
- **FR-012**: System MUST allow a user to permanently delete a brand they own.
- **FR-013**: System MUST require the user to explicitly confirm brand deletion by re-entering the brand's exact name before the deletion is carried out.
- **FR-014**: When a brand is deleted, the system MUST remove its database record, and MUST attempt to remove its stored logo asset (if one exists) as part of the same operation; a storage cleanup failure MUST be logged for operator follow-up but MUST NOT prevent the database record from being removed. This action MUST NOT be reversible and MUST NOT be implemented as a soft delete/trash state.
- **FR-015**: System MUST NOT limit deletion to brands with no logo — deleting a brand with an existing logo MUST succeed and clean up that logo.

### Key Entities

- **Brand**: A distinct product/company identity that a single user creates and manages content generation for. Has a name (unique per owner, case-insensitive), an optional logo image, and a creation date. Owned by exactly one user; ownership cannot be transferred or shared in this phase.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user can create their first brand and see it appear in their brand list in under 1 minute from arriving at the brand list page.
- **SC-002**: 100% of attempts by a user to view, modify, or delete a brand they don't own are blocked, and are indistinguishable from that brand not existing.
- **SC-003**: A user with up to 50 brands can locate and open any specific one of them in under 10 seconds.
- **SC-004**: 100% of successful brand deletions remove the database record and attempt logo asset cleanup as part of the same operation; absent a storage failure, this leaves no trace of the logo asset behind, verified immediately after deletion. A storage cleanup failure is logged for operator follow-up rather than automatically retried — it does not block or reverse the deletion itself.
- **SC-005**: 100% of duplicate-name brand creation attempts are rejected with an immediate, clear message, and never result in a duplicate record.
- **SC-006**: 100% of accidental-deletion attempts (confirmation step not completed correctly) leave the brand fully intact.

## Assumptions

- Brand kit completion status is out of scope for this phase — it's introduced by the Brand Kit phase. Brand list/detail views here surface only name, logo, and creation date.
- No other resource types (brand kit, provider keys, generations) exist in the data model yet at this phase, so hard-deleting a brand in this phase only needs to remove the brand's own record and its logo asset. Cleaning up those other resource types on brand deletion will be addressed when the phases that introduce them land.
- Logo uploads accept common web image formats (PNG, JPEG, WebP) up to 5 MB.
- Brand logo images are stored at a stable, unguessable location and are treated as shareable/public once uploaded, consistent with how other image assets in this product are handled — access control on the asset URL itself is not part of this phase.
- There is no cap on the number of brands a single user may create in this phase; usage limits are not part of this phase's scope.
- "Signed-in user" here refers to an authenticated account exactly as established by the existing authentication feature — no new account/session concepts are introduced.
