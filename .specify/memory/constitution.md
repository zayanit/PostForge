<!--
Sync Impact Report
Version change: [TEMPLATE] → 1.0.0 (initial ratification)
Modified principles: N/A (first concrete adoption from template placeholders)
Added sections:
  - Core Principles (10 principles: Specification First, Single Source of Truth,
    Small Independent Features, MVP First, Consistency Over Cleverness,
    Security by Default, Strong Typing, Documentation as Code,
    Review Before Merge, Ship Value Frequently)
  - Product Scope & Technical Architecture (mission, MVP scope, modular monolith,
    repo layout, technology stack, AI provider abstraction, prompt management)
  - API & Data Standards (REST versioning, response envelope, database change process)
  - Development Workflow (lifecycle, branching, PR requirements, Definition of Done,
    dependency policy, documentation policy, ADRs, testing philosophy,
    logging/observability, performance guidelines, AI agent role assignments)
Removed sections: none (template placeholders only)
Templates requiring updates:
  ✅ .specify/templates/plan-template.md — Constitution Check gate is derived dynamically
     from this file at plan time; no hardcoded principle list to edit.
  ✅ .specify/templates/spec-template.md — no constitution-specific hardcoded references found.
  ✅ .specify/templates/tasks-template.md — no constitution-specific hardcoded references found.
  ✅ .claude/skills/speckit-*/SKILL.md — reference constitution.md generically by path, no
     agent-specific (e.g. CLAUDE-only) naming found requiring correction.
Follow-up TODOs:
  - TODO(RATIFICATION_DATE): Original ratification date not supplied by user; set to the
    date this constitution was first authored in-repo (2026-07-18) pending confirmation.
-->

# PostForge AI Constitution

**Project:** PostForge AI
**Domain:** https://post-forge.app

## Purpose

This Constitution defines the engineering principles, architectural standards, and
development rules governing the PostForge AI project. It ensures that every
contributor — human or AI — builds the application consistently, predictably,
securely, and with long-term maintainability in mind. This document is the highest
authority within the repository: if an implementation conflicts with this
Constitution, the Constitution takes precedence.

## Project Mission

PostForge AI enables creators, businesses, and agencies to generate high-quality
social media content using their own AI providers while maintaining complete
ownership of their AI usage and branding. The project emphasizes simplicity, speed,
maintainability, security, and scalability without sacrificing developer experience.

## MVP Philosophy

The MVP exists to validate the product, not to solve every future problem. Every
implementation MUST favor simplicity, reliability, and readability over premature
optimization. When two valid solutions exist, the simpler one MUST be chosen.
Features not required for the MVP MUST be intentionally deferred rather than
partially implemented.

## Core Principles

### I. Specification First

No implementation MAY begin without an approved specification. Every feature MUST
have a Specification, a Technical Plan, and a Task Breakdown before development
starts. Rationale: prevents undirected work and ensures AI and human contributors
share a single, reviewable definition of what is being built before code is written.

### II. Single Source of Truth

Specifications are authoritative; code MUST follow specifications. If an
implementation changes in a way that diverges from its specification, the
specification MUST be updated before merging. Rationale: keeps specs from rotting
into stale documentation and preserves them as a reliable reference for future work.

### III. Small Independent Features

Features MUST remain small, isolated, and independently deployable whenever
possible. Large multi-feature pull requests MUST be avoided. Each feature MUST
solve one problem well. Rationale: small units reduce review burden, isolate risk,
and keep the main branch releasable at all times.

### IV. MVP First

Only what provides value today MUST be built. Speculative abstractions, unused
features, unnecessary configuration, and premature optimization MUST be avoided.
Future ideas belong in the roadmap, not in production code. Rationale: protects
velocity and keeps the codebase legible while the product is still validating
core assumptions.

### V. Consistency Over Cleverness

Readable code MUST be preferred over clever code. Consistency across the repository
is more valuable than any individual optimization; every module SHOULD feel like it
was written by the same developer. Rationale: with multiple human and AI
contributors, predictable patterns matter more than local cleverness for long-term
maintainability.

### VI. Security by Default (NON-NEGOTIABLE)

Security is never optional. Sensitive information MUST NOT be committed, logged,
exposed, or hardcoded. All secrets MUST be encrypted and managed securely. User API
keys MUST be encrypted, validated before storage, and MUST remain inaccessible after
creation. Only `.env.example` MAY be committed; production secrets are managed
externally. Authentication is handled exclusively by Supabase Auth, and authorization
MUST be enforced server-side — client-side authorization MUST NOT be trusted.
Rationale: PostForge AI handles user-owned AI provider credentials; a single leak
undermines the product's core trust proposition.

### VII. Strong Typing

Every interface MUST be explicitly typed. Implicit behavior MUST be avoided.
Contracts between frontend and backend MUST be deterministic and documented.
Rationale: explicit types catch integration errors at build time and make
generated/AI-authored code easier to verify.

### VIII. Documentation as Code

Documentation evolves alongside implementation. A feature is considered incomplete
if its documentation is outdated. Rationale: documentation that lags behind code
becomes actively misleading, especially for AI agents operating from written specs.

### IX. Review Before Merge

No code reaches the default branch without review. All pull requests MUST be
checked for architecture compliance, specification compliance, code quality,
security, and readability. Rationale: review is the last gate before shared state
changes and MUST NOT be skipped regardless of contributor (human or AI).

### X. Ship Value Frequently

Working software MUST be delivered in small increments. Small releases reduce risk
and accelerate feedback. Rationale: frequent shipping keeps validation loops short
during the MVP phase.

## Product Scope

PostForge AI is an AI content generation platform. It is explicitly **not** an
all-in-one social media management platform. The MVP scope is limited to: Brand
management, Brand Kit, AI generation, and Generation history. Scheduling,
publishing, analytics, billing, and collaboration are future enhancements and MUST
NOT be built into the MVP surface. The architecture SHOULD make future expansion
(additional AI providers, more social platforms, scheduling, publishing, analytics,
billing, collaboration, AI agents, automation) straightforward, but these future
possibilities MUST NOT complicate today's MVP implementation.

## Technical Architecture

The application uses a **Modular Monolith** architecture. The codebase MUST remain
modular without introducing unnecessary distributed complexity. Major modules
include: Authentication, Users, Brands, Brand Kit, AI Providers, Content Generation,
History, Storage, and Admin. Each module owns its own business logic; modules
communicate through well-defined interfaces.

**Repository layout** (Monorepo):

```
postforge/
apps/
    frontend/
    backend/
packages/
    shared-types/
    ui/
    config/
specs/
docs/
scripts/
.github/
```

Shared code belongs inside `packages`; feature-specific logic belongs inside the
owning application.

**Technology stack** — no alternative frameworks or datastores MAY be introduced
without an approved ADR:

- Frontend: Next.js 14, TypeScript, App Router, Tailwind CSS, shadcn/ui, TanStack
  Query, React Hook Form, Zod, Zustand.
- Backend: FastAPI, Python, Pydantic, SQLAlchemy, Alembic (Modular Monolith).
- Database: Supabase (PostgreSQL, Authentication, Storage, Vault) — the single
  source of truth for authentication and persistent data.
- Deployment: Bunny Magic Containers, targeting Development and Production;
  additional environments require approval.

**AI Architecture**: the application MUST NOT communicate directly with AI
providers. All requests pass through the Provider Abstraction Layer:

```
Generation Service → Provider Factory → Provider (Gemini | OpenAI | OpenRouter)
```

This guarantees extensibility without changing business logic.

**Prompt Management**: prompts are product assets and MUST NOT be hardcoded inside
application logic. Prompts are stored separately and version controlled (e.g.
`backend/prompts/instagram_post.md`). Prompt changes require review.

## API & Data Standards

The backend exposes versioned REST APIs (e.g. `/api/v1/auth`, `/api/v1/brands`,
`/api/v1/generation`). Breaking changes require a new API version.

Successful responses follow `{"success": true, "data": {}}`; errors follow
`{"success": false, "error": {"code": "ERROR_CODE", "message": "Human readable message"}}`.
All endpoints MUST follow the same contract.

Database schema changes require a migration, a documentation update, and a
specification update. Manual production database edits are prohibited.

Business logic belongs inside services; API routes MUST remain thin (validate,
authorize, delegate) while services implement business rules.

The frontend MUST prioritize accessibility, responsive design, predictable
navigation, and reusable components. Duplicate UI implementations MUST be avoided;
shared UI belongs in the shared UI package.

## Development Workflow

Every feature follows the same lifecycle, and skipping stages is prohibited:

```
Idea → Specification → Architecture Review → Implementation Plan → Task Breakdown
→ Backend Development → Frontend Development → Review → Testing → Merge
```

**Branch strategy**: `main` remains production-ready at all times. Feature work is
isolated in branches (e.g. `feature/auth`, `feature/brands`, `feature/history`).
Large long-running branches MUST be avoided.

**Pull request requirements**: every PR MUST reference its specification, satisfy
acceptance criteria, pass linting, pass builds, pass tests, and receive review
approval. PRs failing these requirements MAY NOT be merged.

**Definition of Done**: a feature is complete only when its specification is
approved, its plan and tasks are completed, backend and frontend implementation are
done, tests are passing, documentation is updated, code is reviewed, and acceptance
criteria are satisfied. Anything less is work in progress.

**Dependency policy**: new dependencies require justification against maintenance,
community adoption, security, bundle size, and necessity. Existing project
dependencies MUST be preferred whenever possible.

**Documentation policy**: every significant change MUST update specifications, API
documentation, architecture documentation, and ADRs where applicable.

**Architecture Decision Records**: major technical decisions (framework changes,
database strategy, authentication changes, AI provider architecture, deployment
architecture) require an ADR explaining *why* the decision was made, not just what
changed.

**Testing philosophy**: testing prioritizes confidence over coverage percentages,
in order: business logic, API behavior, critical user flows, regression prevention.
Brittle tests that discourage refactoring MUST be avoided.

**Logging & observability**: logs MUST be structured, actionable, and
privacy-safe. Sensitive information MUST NOT appear in logs. Errors SHOULD include
sufficient context for troubleshooting without exposing user data.

**Performance guidelines**: optimize only when measurements indicate a real
problem — measure first, improve second.

**AI development workflow**: the project uses specialized AI agents with defined
responsibilities:

- ChatGPT — Product Management, Specifications, Architecture, Database Design, API
  Contracts, Roadmaps.
- Claude Code — Backend implementation, Refactoring, Architecture enforcement,
  Repository organization.
- GLM — Boilerplate, Utilities, Feature implementation, Repetitive development
  tasks.
- Gemini (AntiGravity) — Frontend implementation, Components, Layouts, Forms,
  Responsive design.
- Claude — Code Review, Security Review, Specification Validation, Architecture
  Validation.

## Governance

This Constitution supersedes all other project practices. Any proposal that
violates these principles MUST either be rejected or amend this Constitution
through an approved architectural decision — there are no exceptions.

**Amendment procedure**: amendments are proposed via pull request against this
file, MUST include an updated Sync Impact Report, and MUST be reviewed and
approved before merge, following the same Review Before Merge principle applied
to code.

**Versioning policy**: this Constitution follows semantic versioning.
- MAJOR: backward-incompatible governance or principle removals/redefinitions.
- MINOR: new principle or section added, or materially expanded guidance.
- PATCH: clarifications, wording, and non-semantic refinements.

**Compliance review**: all pull requests and specifications MUST be checked for
compliance with this Constitution as part of the standard Review Before Merge and
Specification First principles. Complexity that deviates from these principles
MUST be explicitly justified in the specification or PR description.

**Guiding statement**: PostForge AI is built on a simple philosophy — build small,
build well, ship often. Every decision should move the project toward a
maintainable, secure, and scalable product while keeping the developer experience
enjoyable and the implementation intentionally simple.

**Version**: 1.0.0 | **Ratified**: 2026-07-18 | **Last Amended**: 2026-07-18
