# Research: Accessible Sign-up Flow

## Decision: Reuse the existing signup page and Supabase client

The repository already has `frontend/app/(auth)/signup/page.tsx`, including eight-character password validation and `supabase.auth.signUp`. The defect is that `/login` has no visible route to it. Reusing this page preserves the existing authentication and profile-trigger behavior.

## Decision: Use Next.js `Link` for page-to-page navigation

`Link` provides accessible, client-side navigation and is already used by the auth pages. The login page will link to `/signup`, and signup will link back to `/login`.

## Decision: Add browser-level coverage

The user-visible defect is route discoverability, so Playwright is the appropriate test layer. The test will verify both directions and the existing validation/success feedback without introducing a backend contract.

## Alternatives considered

- Adding a new backend signup endpoint: rejected because Supabase Auth already owns account creation and the existing page works through it.
- Redirecting automatically after signup: not required for the requested discoverability fix; the current page's explicit success state is preserved.
