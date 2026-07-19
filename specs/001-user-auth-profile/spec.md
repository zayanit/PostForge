# Feature Specification: User Authentication & Profile

**Feature Branch**: `001-user-auth-profile`

**Created**: 2026-07-19

**Status**: Draft

**Input**: User description: "Read phase 1 form @docs/implementation-plan.md and according to the best practices of Github's speckit create the first spec"

## Clarifications

### Session 2026-07-19

- Q: What minimum password strength standard should signup enforce? → A: Minimum 8 characters, no composition rules (Supabase Auth default)
- Q: Must a new account verify their email before they can sign in and use the product? → A: No verification required — full access immediately after signup
- Q: What should happen after repeated failed login attempts for the same account? → A: Temporary lockout after 5 consecutive failed attempts for that account

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create an account (Priority: P1)

A new visitor creates an account with an email address and password so they can start using the product.

**Why this priority**: Nothing else in the product is reachable without an account. This is the entry point for every other feature (brands, brand kits, generation, history).

**Independent Test**: Can be fully tested by submitting a signup form with a valid email and password and verifying a new account and profile exist, independent of any other feature being built yet.

**Acceptance Scenarios**:

1. **Given** a visitor is on the signup page, **When** they submit a valid, unused email address and a password meeting the minimum requirements, **Then** an account is created and a profile record is created for them.
2. **Given** a visitor is on the signup page, **When** they submit an email address that is already registered, **Then** the system rejects the signup with a clear error and does not create a duplicate account.
3. **Given** a visitor is on the signup page, **When** they submit a password that does not meet the minimum requirements, **Then** the system rejects the signup and explains why.

---

### User Story 2 - Log in and log out (Priority: P1)

A returning user logs in with their email and password to access their account, and can log out when finished.

**Why this priority**: Equally foundational to signup — without reliable login/logout, returning users cannot use the product and sessions cannot be trusted to be private.

**Independent Test**: Can be fully tested by logging in with a known account's credentials, confirming access to authenticated areas, then logging out and confirming those areas are no longer accessible.

**Acceptance Scenarios**:

1. **Given** a registered user on the login page, **When** they submit their correct email and password, **Then** they are signed in and taken to their dashboard.
2. **Given** a registered user on the login page, **When** they submit an incorrect password, **Then** the system rejects the login with a clear, generic error that does not reveal whether the email exists.
3. **Given** a signed-in user, **When** they choose to log out, **Then** their session ends and any subsequent attempt to reach an authenticated page redirects them to login.
4. **Given** a user whose session has expired, **When** they attempt to perform an authenticated action, **Then** the system prompts them to log in again rather than exposing an error or stale data.

---

### User Story 3 - View and edit profile (Priority: P2)

A signed-in user views their account profile and updates their display name and avatar.

**Why this priority**: Valuable and expected, but the product is still usable in a limited fashion (Phase 1 checkpoint) without it; it depends on Stories 1 and 2 being in place first.

**Independent Test**: Can be fully tested by signing in as a user, viewing the profile page, changing the display name and avatar URL, saving, and confirming the new values persist across a page reload.

**Acceptance Scenarios**:

1. **Given** a signed-in user on their account settings page, **When** the page loads, **Then** it displays their current email, full name, and avatar.
2. **Given** a signed-in user editing their profile, **When** they submit a valid full name and avatar URL, **Then** the changes are saved and reflected immediately.
3. **Given** a signed-in user editing their profile, **When** they submit an invalid value (e.g., a name that is empty/too short, or an avatar value that is not a URL), **Then** the system rejects the change and explains why, leaving the previous values intact.

---

### User Story 4 - Reset a forgotten password (Priority: P3)

A user who forgot their password requests a reset link by email and sets a new password.

**Why this priority**: Important for real-world usability and account recovery, but not required to demonstrate the core value of the product during initial development.

**Independent Test**: Can be fully tested by requesting a password reset for a known account, using the resulting link to set a new password, and confirming login works with the new password and not the old one.

**Acceptance Scenarios**:

1. **Given** a user on the login page who forgot their password, **When** they request a password reset for their registered email, **Then** they receive an email with a link to set a new password.
2. **Given** a user requests a password reset for an email that is not registered, **When** the request is submitted, **Then** the system responds the same way as for a registered email, without revealing whether the account exists.
3. **Given** a user follows a valid reset link, **When** they submit a new password meeting the minimum requirements, **Then** their password is updated and they can log in with it.

---

### Edge Cases

- What happens when a visitor tries to sign up with an email that's already registered? (Story 1, Scenario 2)
- What happens when a user repeatedly enters incorrect login credentials? After 5 consecutive failed attempts for the same account, the system MUST apply a temporary lockout (not permanent, not indistinguishable from an outage) before further attempts are accepted, while still returning the same generic error message on each failure.
- What happens when a user's session expires mid-task? System MUST redirect to login without silently discarding unsaved input where avoidable.
- What happens when a user submits a profile update with a whitespace-only name or a malformed avatar value?
- What happens when a signed-in user closes the browser without logging out? Session MUST expire based on standard token expiry rather than remaining valid indefinitely.
- What happens when a password reset link is reused after already being used once, or has expired?
- What happens when a user attempts to reach any authenticated page (dashboard, brands, account settings) without ever signing in?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow a visitor to create an account using an email address and a password.
- **FR-002**: System MUST reject signup attempts using an email address that is already registered, without creating a duplicate account.
- **FR-003**: System MUST require passwords to be at least 8 characters long at signup (no additional composition rules), and MUST communicate this requirement clearly when not met.
- **FR-004**: System MUST create exactly one profile record for each new account at signup.
- **FR-005**: System MUST allow a registered user to log in with their email and password and establish an authenticated session, without requiring email address verification first.
- **FR-006**: System MUST reject login attempts with incorrect credentials using a generic error that does not reveal whether the email is registered.
- **FR-006a**: System MUST temporarily lock out login attempts for an account after 5 consecutive failed attempts, automatically lifting the lockout after a short delay rather than requiring manual intervention.
- **FR-007**: System MUST allow a signed-in user to log out, immediately ending their session.
- **FR-008**: System MUST deny access to any authenticated page or account data when there is no valid, current session, redirecting to login instead.
- **FR-009**: System MUST allow a signed-in user to view their own profile information (email, full name, avatar).
- **FR-010**: System MUST allow a signed-in user to update their own full name and avatar, and MUST reject updates that fail validation (e.g., name outside allowed length, avatar not a valid URL) while leaving prior values unchanged.
- **FR-011**: System MUST ensure a user can only ever view or modify their own profile, never another user's, even if another user's identifier is guessed or supplied.
- **FR-012**: System MUST allow any user to request a password reset via their registered email, and MUST respond identically regardless of whether that email is registered.
- **FR-013**: System MUST allow a user who follows a valid, unexpired password reset link to set a new password, after which the old password no longer works.
- **FR-014**: System MUST support account creation and login using email/password only for this feature; sign-in with third-party identity providers (e.g., Google, GitHub) is out of scope for this spec (see Assumptions).

### Key Entities

- **Account**: The authentication identity for a user — email address, password credential, and email verification state. One account grants access to everything the user owns.
- **Profile**: Editable, user-facing account information linked one-to-one with an Account — full name and avatar. Exists as soon as the account is created, even before the user fills anything in.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new visitor can go from landing on the signup page to reaching their dashboard in under 2 minutes.
- **SC-002**: A returning user can go from landing on the login page to reaching their dashboard in under 15 seconds, given correct credentials.
- **SC-003**: 100% of profile update attempts containing invalid data are rejected with an explanatory message, and 0% result in corrupted or partially-saved profile state.
- **SC-004**: In testing, 0 instances of one user viewing or modifying another user's profile are observed, across all attempted access patterns.
- **SC-005**: A user who requests a password reset can regain access to their account using only the emailed link, without support intervention, in under 5 minutes.
- **SC-006**: 100% of attempts to reach an authenticated page without a valid session are redirected to login rather than exposing any account data.

## Assumptions

- Email/password is the only signup and login method in scope for this feature. Third-party OAuth (Google, GitHub, etc.) is not mentioned anywhere in the approved implementation plan's Phase 1 scope, so it is excluded here; adding it would materially expand this feature's surface area (provider app registration, consent screens, account-linking rules).
- Authentication primitives (credential storage, password hashing, session/JWT issuance, password-reset token generation) are provided by Supabase Auth rather than being built from scratch by this feature, consistent with the implementation plan's technology stack.
- Email verification is not required to sign in or use the product; accounts have full access immediately after signup. Supabase Auth's confirmation-email feature, if enabled at the platform level for anti-abuse purposes, does not gate access.
- Account deletion and deactivation are out of scope for this feature; only creation, authentication, session termination, password reset, and profile viewing/editing are included.
- This spec covers only authentication and the user's own profile (the `profiles` table). Brand management, Brand Kit, provider key connections, content generation, history, and the operator admin area are separate, subsequent specs that depend on this one.
- A profile's full name has a minimum and maximum reasonable length, and its avatar field must be a well-formed URL when present, matching the validation already defined for the `profiles` table in the implementation plan; exact bounds are an implementation detail, not a product decision requiring clarification.
