# Feature Specification: Brand Kit Interview

**Feature Branch**: `006-brand-kit`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Read docs/implementation-plan.md and create specification for Phase 5: Brand Kit."

## Clarifications

### Session 2026-07-29

- Q: What does the Name step do? → A: It edits the existing brand name; it does not create a separate kit name or a second brand.
- Q: How should unauthorized access to another user’s kit respond? → A: Return a generic not-found response with no kit data, without revealing whether the brand exists.
- Q: How should simultaneous saves from multiple tabs or sessions be handled? → A: The last successful save wins.
- Q: How many colors are required for a complete kit? → A: Require 1–3 valid hexadecimal colors.
- Q: When should wizard progress be saved? → A: Auto-save after each completed step and support an explicit save action.

## User Scenarios & Testing

### User Story 1 - Complete a brand kit (Priority: P1)

A signed-in brand owner answers a guided set of questions so PostForge can capture the brand context used by future content generation.

**Why this priority**: The brand kit is the Phase 5 foundation for consistent brand-aware generation.

**Independent Test**: Create a brand, answer all six questions with valid values, complete the interview, and verify the answers, summary, and complete status are shown after reload.

**Acceptance Scenarios**:

1. **Given** a signed-in owner opens a brand with no kit answers, **When** they start the interview, **Then** the wizard presents six clearly ordered questions.
2. **Given** the owner supplies all required answers and optionally supplies the two optional answers, **When** they finish the interview, **Then** the kit is saved with status `complete`, a completion time, and a readable summary containing the brand context.
3. **Given** a completed kit, **When** the owner revisits it, **Then** the saved answers and completion summary are displayed and can be edited.

### User Story 2 - Save and resume partial answers (Priority: P1)

A brand owner can save progress with zero or some answers and return later without losing the work already entered.

**Why this priority**: The checkpoint explicitly requires the interview to work with zero answers and complete kits; partial progress makes the six-step flow usable in practice.

**Independent Test**: Open a new kit, save no answers and verify `not_started`; save only some answers and verify `in_progress`; reload and confirm those answers remain available for continuation.

**Acceptance Scenarios**:

1. **Given** a brand has no saved kit, **When** its kit is requested, **Then** the system returns an empty kit with status `not_started`.
2. **Given** the owner saves at least one answer but has not completed every required field, **When** the kit is requested, **Then** it returns the saved answers with status `in_progress`.
3. **Given** an in-progress kit, **When** the owner moves backward or leaves and later returns, **Then** the wizard restores the saved answers and current progress.
4. **Given** the owner omits an optional answer, **When** all required answers are valid, **Then** the kit can still reach `complete` and the summary identifies the optional value as unspecified.

### User Story 3 - Keep kits private to their owner (Priority: P1)

A brand owner can manage only kits belonging to their own brands, while other users receive a generic not-found response.

**Why this priority**: Brand isolation is a non-negotiable product and security rule.

**Independent Test**: Authenticate as two users, create a brand for each, and verify neither user can read or update the other user’s kit.

**Acceptance Scenarios**:

1. **Given** an authenticated owner requests their own brand kit, **When** the request is processed, **Then** the kit is returned.
2. **Given** an authenticated user requests another user’s brand kit by identifier, **When** the request is processed, **Then** no kit data is disclosed and a generic not-found response is returned.
3. **Given** a visitor has no valid session, **When** they request or update a brand kit, **Then** the request is rejected without exposing kit data.

### Edge Cases

- A kit is requested before any answers have been saved.
- A required answer is blank, whitespace-only, or outside its allowed length.
- A tone value is not one of the five supported choices.
- More than three colors are submitted, or a color is not a valid hexadecimal value.
- A user tries to mark a kit complete while a required answer is missing.
- A save is repeated with the same answers and must not create duplicate kits.
- Two tabs or sessions save different answers for the same brand at nearly the same time.
- A user edits a complete kit back to an incomplete state.
- A user attempts to access a deleted or nonexistent brand.
- A request is made without authentication or with an expired session.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST provide a guided six-question brand kit interview in this order: name, tagline, tone, audience, colors, and avoid words.
- **FR-002**: The Name step MUST edit the existing brand name, and the interview MUST NOT create a separate kit name or a second brand.
- **FR-003**: The tagline MUST be optional and limited to 160 characters when supplied.
- **FR-004**: Tone MUST be required and limited to `formal`, `casual`, `playful`, `professional`, or `friendly`.
- **FR-005**: Audience MUST be required and contain between 2 and 500 non-whitespace characters.
- **FR-006**: Colors MUST contain at least one and no more than three values, and each value MUST be a valid hexadecimal color.
- **FR-007**: Avoid words MUST be optional.
- **FR-008**: The system MUST allow a kit to be read when it has no saved answers and MUST return status `not_started` in that state.
- **FR-009**: The system MUST save partial answers and return status `in_progress` until all required fields are valid.
- **FR-010**: The system MUST allow a kit to be upserted repeatedly without creating duplicate kit records for the same brand; omitted answer fields in a partial save MUST preserve their existing values, explicit null or empty values MUST clear the corresponding field, and when saves overlap the last successful save MUST be retained.
- **FR-011**: The system MUST reject a request to save status `complete` when any required field is missing or invalid.
- **FR-012**: When all required fields are valid, the system MUST derive and save a readable summary containing the brand name, tagline, tone, audience, colors, and avoid-words value or an explicit unspecified value.
- **FR-013**: The system MUST set `completed_at` when a kit becomes complete and MUST clear or update completion state when later edits make it incomplete.
- **FR-014**: The wizard MUST support moving backward, moving forward, editing an existing kit, auto-saving after each completed step, and explicitly saving progress.
- **FR-015**: The wizard MUST provide a completion summary after all required answers are complete.
- **FR-016**: The brand navigation MUST show whether the kit is `not_started`, `in_progress`, or `complete`.
- **FR-017**: Every read and write operation MUST require an authenticated session and verify that the current user owns the requested brand.
- **FR-018**: The system MUST prevent one user from reading, changing, or inferring another user’s kit data, and MUST return a generic not-found response for unauthorized kit access.
- **FR-019**: Validation and authorization failures MUST use the project’s safe error format and MUST NOT expose secrets or unrelated user data.

### Key Entities

- **Brand**: An owner-controlled brand that anchors the kit and retains its existing name.
- **Brand Kit**: One editable kit per brand containing optional tagline and avoid-words values, required tone, audience, and colors, plus status, summary, and completion metadata.
- **Kit Status**: The lifecycle state `not_started`, `in_progress`, or `complete`.

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% of new kits can be opened with zero answers and display a usable `not_started` state.
- **SC-002**: 100% of valid complete-kit submissions preserve all six question values and produce a summary containing each value.
- **SC-003**: 100% of partial saves reload with the previously saved answers and an accurate `in_progress` state.
- **SC-004**: 100% of attempts to save invalid required values are rejected with an actionable validation message and leave the prior valid kit unchanged.
- **SC-005**: 100% of tested cross-user read and write attempts return no other user’s kit data.
- **SC-006**: A new owner can complete the six-question interview in under 5 minutes without needing to know the underlying data model.
- **SC-007**: Returning to a saved kit restores the owner’s progress in one page load.

## Assumptions

- The existing brand record and ownership rules are reused; this feature does not add sharing or collaboration.
- Each brand has at most one kit, and deleting a brand removes its kit according to the existing hard-delete behavior.
- The six-question set and tone values are fixed for this phase; custom questions and custom tone values are out of scope.
- The summary is derived deterministically from the saved answers and does not require an external AI provider.
- The wizard auto-saves on step completion and also provides an explicit progress-save action; exact UI control wording can follow established product patterns.
- Brand-kit zero-answer and complete-kit checks are applicable because this feature implements the Brand Kit capability; provider and generation checks remain out of scope until their dependent phases.
