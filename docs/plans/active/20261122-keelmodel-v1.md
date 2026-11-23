# Execution Plan: KeelModel v1

Date: 2026-11-22

## Status

Active

## Outcome

Implement the first useful KeelModel release as a strict, sync-first, PostgreSQL data SDK with YAML-owned schemas, explicit module composition, structured data operations, and optional capabilities. Keep `keelpolicy` as an independent Python package in the same repository for v1.

## Context

- [Contract spec](../../../history/20261122-keelmodel-implementation/contract-spec.md)
- [Technical design](../../../history/20261122-keelmodel-implementation/technical-design.md)
- [Approach](../../../history/20261122-keelmodel-implementation/approach.md)
- [Proposed structure](../../../history/20261122-keelmodel-implementation/structure.md)
- [Repository workflow](../../WORKFLOW.md)

## Scope

In scope:

- Python package/tooling foundation for `keelmodel` and `keelpolicy`.
- Strict model YAML validation and deterministic generated Python.
- Explicit module registration.
- Sync PostgreSQL/SQLAlchemy CRUD, query, transaction, and atomic bulk operations.
- Core policy evaluation and authorization, after security review.
- Alembic migration drafts.
- Optional field authorization and audit extensions after core contracts prove stable.

Out of scope:

- Async SDK, non-PostgreSQL backends, authentication/user storage, HTTP API, UI, workflow engine, automatic module discovery, generic hooks, soft delete, DataView, outbox/search worker.
- Authorization enforcement before the required security design review.

## Approach

1. Establish package layout and reproducible tests/linting with uv.
2. Freeze remaining model schema decisions and implement strict validator/generator.
3. Implement model runtime, registration and synchronous persistence contracts.
4. Complete security review before authorization implementation; implement keelpolicy core and KeelModel enforcement only after gate passes.
5. Add Alembic drafts and validate an example module.
6. Implement optional field authorization and audit after core acceptance and their record contracts are finalized.

## Risks And Recovery

- Public YAML/API changes are costly after release: mark proposed details and test fixtures before treating them as compatibility promises.
- Authorization errors can expose data: fail closed and do not implement enforcement until reviewed.
- Preserve existing harness/docs/history files; do not stage or commit.
- No database schema is in production; early implementation can be revised, but emitted migration drafts must never auto-apply.

## Progress

- [x] Initialize Git repository (no commit created).
- [x] Create uv package foundation and dependency/tooling configuration; import smoke tests and package build pass.
- [x] Implement strict initial model YAML parsing and deterministic Python model generation.
- [x] Implement initial module manifest parsing and explicit registration.
- [x] Add initial SQLAlchemy/PostgreSQL model mapping and metadata DDL proof.
- [x] Add structured basic check-expression validation and PostgreSQL DDL compilation proof.
- [x] Implement sync KeelModel runtime with create/get/update/delete/query/bulk.
- [x] Add input/output type coercion and validation.
- [x] Add structured filter expression compilation.
- [x] Add operation context and typed error taxonomy.
- [x] Implement Alembic migration draft generator (reviewable, no DB changes).
- [x] Implement keelpolicy YAML parser and deny-overrides evaluator.
- [x] Add optional AuthorizationProvider integration (gated, not yet security-reviewed).
- [x] PostgreSQL integration test with real database (3 tests pass when daemon runs).
- [x] Relations: many_to_one, one_to_one (unique FK), one_to_many via mapped_by.
- [x] Named mixins: uuid_pk, timestamps; unique/index constraints.
- [x] Audit extension: same-transaction records via before_flush, field redaction.
- [x] Example sales module: Customer, Invoice, InvoiceLine with relations + mixins.
- [x] DB safety: demo/stress require explicit KEELMODEL_RESET=1; per-test table cleanup only.
- [x] Shared atomic transaction contract (transaction context + _commit defer).
- [x] Strict input validation (boolean/integer/datetime-tz/url/enum negative cases).
- [x] Record-level authz: allow-conditions to SQL for query, per-record check for get/update/delete.
- [x] Module boundary: relation to other module's private model requires declared dep; target must be public.
- [x] Audit: factory-scoped listener (no global leak), no auto-DDL at init, explicit create_all.
- [x] Migration drafts: revision header, FK columns for relations, unique/index.
- [ ] Security review of authorization design before enforcement is enabled by default.
- [ ] Field-level auth enforcement depth (read/filter/order separation).
- [ ] Generated model classes used by runtime (currently internal map_model).

**P2 scope note**: plan declared PostgreSQL-only, but code/tests now prove
MySQL + SQLite via the same abstraction. Keeping multi-dialect as a v1
capability (it cost dialect-aware type mapping + two real bug fixes).
Compatibility contract: UUID/text/datetime/enum/relations work across all
three; JSON-based types map to JSONB on Postgres only.
- [ ] Sync persistence API and atomic bulk.
- [ ] Security review, then keelpolicy and core auth.
- [ ] Alembic drafts and representative module acceptance.
- [ ] Optional field authorization and audit extensions.

## Decisions

- 2026-11-22: `keelpolicy` is a sibling Python package under `src/`, in the same repository; dependency is one-way from KeelModel to KeelPolicy.
- 2026-11-22: Sync-only first; PostgreSQL first; YAML schema and policy are separate sources of truth.
- 2026-11-22: default deny, deny-overrides, denied reads omit fields, denied writes reject the full operation, bulk is atomic.
- 2026-11-22: package foundation may proceed; authorization enforcement waits for security review.

## Validation

- Focused proof: import smoke tests, pytest, Ruff, package build/install.
- Integration or end-to-end proof: isolated PostgreSQL tests once runtime operations exist.
- Repository-required checks: read `docs/WORKFLOW.md`; no existing application/test validation commands were present at plan creation.

## Result

Implementation is in progress. Record verified outcomes and limitations before closing this plan.
