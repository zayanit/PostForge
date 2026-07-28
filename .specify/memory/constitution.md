<!--
SYNC IMPACT REPORT
==================
Version change: 1.1.0 → 2.0.0
Bump rationale: MAJOR - Updated the fixed frontend version and replaced unconditional
  future-capability completion checks with phase-aware applicability. The latter
  changes which checks block earlier features and is backward-incompatible governance.

Modified principles:
  - III. Tech Constraints: Next.js 14 → Next.js 15
  - VII. Definition of Done: unconditional future-capability checks → universal plus
    phase-aware capability checks with documented N/A rules

Added sections: None
Removed sections: None

Templates and guidance status:
  - .specify/templates/plan-template.md ✅ Updated phase-aware Constitution Check guidance
  - .specify/templates/spec-template.md ✅ Updated phase dependency/applicability guidance
  - .specify/templates/tasks-template.md ✅ Updated phase-aware DoD task guidance
  - .specify/templates/checklist-template.md ✅ Updated /speckit.checklist command references
  - .specify/templates/agent-file-template.md ✅ Not present in this initialized template set
  - .opencode/commands/speckit.*.md ✅ Reviewed; no version-specific or unconditional DoD rules
  - README.md ✅ Updated runtime version and implemented-feature status
  - CLAUDE.md ✅ Updated implemented-feature status; existing Next.js 15 guidance retained
  - docs/implementation-plan.md ✅ Updated Next.js version and phase-aware verification checklist
  - specs/004-provider-keys/plan.md ✅ Constitution blockers resolved against v2.0.0

Deferred TODOs: None
-->

# PostForge Constitution

## Core Principles

### I. Product Truth

PostForge is a multi-brand SaaS for generating social images with the following foundational rules:

- Tenancy MUST be based on Brand; every resource belongs to exactly one brand
- One user owns brands; sharing is not supported; only owner role exists
- No billing in MVP; users MUST provide their own API keys (BYOK model)
- Image generation is the sole product **capability** — i.e., the only thing a Brand can
  be used to *do*. This does not restrict foundational account infrastructure (user
  authentication, session management, user profile) that must exist before a Brand can
  be created in the first place; such infrastructure is a prerequisite, not a competing
  product capability, and is governed by Principles III and VI instead.

### II. Non-Negotiables

These constraints MUST NOT be violated under any circumstances:

- **Brand Isolation**: Every resource (generations, brand kits, keys) MUST belong to exactly one brand
- **Hard Delete**: When a user deletes a brand or generation, the system MUST remove both database rows AND stored assets; soft delete is forbidden
- **Key Secrecy**: Provider keys MUST NEVER appear in logs; keys MUST NEVER be sent to the client
- **Official Endpoints Only**: The system MUST use only official API endpoints for OpenAI and Gemini; no proxies or unofficial APIs
- **PNG Output Only**: All generated images MUST be output as PNG format

### III. Tech Constraints

The technology stack is fixed for MVP:

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 15 monolith |
| Backend | FastAPI |
| Auth, DB, Vault, Storage | Supabase |
| Hosting | Bunny Magic Containers |
| Providers | OpenAI, Gemini |
| Capability | Image generation is the only product capability (see Principle I for the account-infrastructure exemption) |

Deviations from this stack require explicit constitutional amendment.

### IV. Data Rules

All data persistence MUST follow these rules:

- **Generation Records**: MUST store prompt, provider, model, dimensions preset, and image storage path
- **Brand Kit**: MUST store brand kit answers and derived brand summary
- **Provider Keys**: MUST be stored in Supabase Vault; database MUST reference keys by opaque IDs only, never storing raw key values

### V. UX Rules

User experience MUST adhere to these patterns:

- Free-form prompt is the primary input mechanism for image generation
- Brand kit MUST be created via an interview flow; direct editing is secondary
- Platform preset (dimensions) MUST be selected for each generation; no default fallback
- History MUST be first-class; MUST be filterable by brand and provider

### VI. Security Rules

Security implementation MUST follow these requirements:

- Supabase Row Level Security (RLS) MUST be enabled on all tables
- Brand ID MUST be verified server-side for all read and write operations; client assertions are insufficient
- Provider API calls MUST originate from server only; client MUST NEVER call providers directly
- Logs MUST contain only request IDs and safe metadata; no keys, tokens, or PII in logs

### VII. Definition of Done

A feature is complete only when all universal checks and every capability check
applicable to the current implementation phase are verified.

Universal checks:

- [ ] Acceptance scenarios for the feature pass at the API, data, and user-facing
      layers it changes
- [ ] Every table introduced or changed has RLS, forced RLS, policies, and required
      privileges verified by direct integration tests; backend-only tables also require
      tests proving client roles are denied
- [ ] Server-side ownership and secret/logging rules are tested for every affected
      read and write operation
- [ ] Every deletable database row, secret, or stored asset affected by the feature
      is physically removed on successful deletion; soft delete is forbidden

Capability checks become mandatory only when their prerequisite capability exists:

- [ ] Brand-kit zero-answer and completed-kit scenarios are required beginning with
      the feature that implements Brand Kit, and for later brand-scoped features whose
      behavior reads or depends on Brand Kit. Before Brand Kit exists, these checks are
      not applicable.
- [ ] OpenAI behavior is required beginning with the feature that first integrates
      OpenAI, and for every later feature that calls or changes that integration.
- [ ] Gemini behavior is required beginning with the feature that first integrates
      Gemini, and for every later feature that calls or changes that integration.
- [ ] Generation lifecycle, platform preset, and PNG-output checks are required
      beginning with the feature that implements image generation, and for later
      features that change generation behavior.

A plan MAY mark a capability check not applicable only when its prerequisite has not
been implemented or the feature cannot affect that capability. The plan MUST record
that rationale. Once a prerequisite capability exists, applicable checks MUST NOT be
deferred merely because they belong to an earlier or later roadmap phase.

## Governance

### Amendment Process

1. Amendments MUST be documented in this file with version increment
2. Changes to Non-Negotiables (Principle II) require explicit justification
3. All dependent templates MUST be reviewed after amendments
4. Sync Impact Report MUST be updated at the top of this file

### Versioning Policy

- **MAJOR**: Backward-incompatible changes to principles or removal of constraints
- **MINOR**: New principles added or existing principles materially expanded
- **PATCH**: Clarifications, wording improvements, non-semantic changes

### Compliance

- All pull requests MUST verify compliance with this constitution
- Plan documents MUST include a Constitution Check section
- Definition of Done checklist MUST be completed before feature merge

**Version**: 2.0.0 | **Ratified**: 2025-01-28 | **Last Amended**: 2026-07-26
