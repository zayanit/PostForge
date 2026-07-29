# Research: Brand Kit Interview

## Decision: Add a dedicated `brand_kits` table with one row per brand

The implementation plan defines `brand_kits.brand_id` as the primary key with `ON DELETE CASCADE`. This naturally enforces one kit per brand and makes brand deletion remove the kit. A missing row represents `not_started`; partial and complete work use the row’s status.

## Decision: Derive status and summary on the server

The backend will validate the six answer fields, derive `not_started`/`in_progress`/`complete`, set `completed_at`, and build the deterministic summary. The client will not submit an authoritative status or summary, preventing inconsistent state and keeping the summary independent of external providers.

## Decision: Serialize saves by locking the owned brand row

The existing stores already lock owned brands for mutations. The Brand Kit store will use the same transaction boundary, so overlapping saves complete in database order and the last successful transaction wins as clarified. No version column or merge algorithm is needed for the single-owner MVP.

## Decision: Clear derived summary when a kit becomes incomplete

The summary is only canonical for a complete set of required answers. When a later edit makes a kit incomplete, the store will set `summary` and `completed_at` to null and derive a new summary only after the required fields are valid again. This prevents future generation flows from consuming stale brand context.

## Decision: Derive brand navigation status from a left join

The current `brands` table does not contain a kit status column. Brand list/detail queries will left join `brand_kits` and default a missing row to `not_started`, allowing the dashboard selector and brand cards to show status without duplicating lifecycle state.

## Decision: Use existing authenticated API and browser patterns

The API will follow `/api/v1/brands/{brand_id}/kit`, `CurrentUserDep`, safe error envelopes, and the existing store dependency pattern. The wizard will use the existing Supabase session access token and `NEXT_PUBLIC_API_URL`, matching current brand and provider-key pages.

## Alternatives considered

- Storing all kit fields directly on `brands`: rejected because the approved schema and one-to-one lifecycle are already modeled as `brand_kits`.
- Letting the browser derive status or summary: rejected because clients cannot be trusted with validation or canonical lifecycle state.
- Adding optimistic version conflicts: rejected for this single-owner MVP because clarified behavior is last successful save wins.
- Calling an AI provider for summary generation: rejected because the Phase 5 template is deterministic and provider integrations belong to later phases.
