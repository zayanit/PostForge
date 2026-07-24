# Phase 1 Data Model: Dockerization

**N/A — no data entities.**

This feature packages existing application code for deployment; it introduces no new
database tables, columns, or persisted records. Supabase (Auth, Database, Vault, Storage)
is unchanged and continues to run externally, per the spec's Assumptions.

The only "state" this feature introduces is process-level and lives entirely in memory
inside the running container (which of the two processes is currently up, whether a
shutdown has been requested) — see `contracts/entrypoint.md` for that behavior contract.
There is nothing here for `/speckit-tasks` to generate a migration or model for.
