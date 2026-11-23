---
status: proposed
last_reviewed: 2026-11-21
superseded_by: []
related_code: []
---

# Brainstorm: KeelModel SDK Design

## Decision

- **Recommendation:** Build KeelModel as a lightweight, code-first Python data SDK for ERP applications. PostgreSQL is the first optimized backend; SQLAlchemy provides persistence internals, while KeelModel owns its public model/query/permission semantics.
- **Decision owner:** User
- **Confidence:** medium — design choices are user-confirmed, but no implementation or workload validation exists.

## Problem and Outcome

Provide reusable low-level data capabilities for ERP modules developed in separate repositories, without building a full ERP, UI builder, application auth system, or heavy framework. Modules compose in one application through explicit dependencies and shared contracts.

## Constraints and Non-Goals

- Code-first; no drag-and-drop schema design.
- PostgreSQL-first with an adapter boundary; do not support more databases in v1.
- Domain models are defined in code and are independent of UI.
- No login/authentication, REST/GraphQL transport, admin UI, ERP workflow engine, or cross-database federation in the SDK core.
- Modules are separate Python packages/repositories, installed and versioned by the consuming application.
- Keep the system lightweight; avoid implicit event handlers, hidden business logic, and integrations inside model lifecycle hooks.

## Evidence

- Decisions in this brief were confirmed interactively by the product owner on 2026-11-21. No implementation evidence exists yet.
- SQLAlchemy is the persistence implementation beneath KeelModel APIs; async API is planned first, sync is a later independent API path.

## Confirmed Design

### Models and fields

- YAML is the model schema source of truth from v1; generated Python classes are committed output and must not be hand-edited.
- YAML is strict and versioned. Use one model per file under module directories such as `modules/sales/models/*.yaml`.
- Generator emits full Python classes into a separate generated directory. CI regenerates and fails with a diff if generated files drift or are edited manually.
- YAML may reference a qualified Python extension class, imported and validated during generation; failure stops generation. Extensions add methods only; fields and relations remain YAML-owned.
- YAML fully expresses declarative schema (fields, relations, constraints). Behavior not expressible declaratively remains in extension code; no per-model schema merge.
- YAML declares capability/field metadata but not concrete authorization policies. Applications own permission names and policy behavior.
- A YAML module manifest declares module version, required/optional dependencies, version ranges, and public model exports; Python package metadata still installs/releases the module.
- Generator output is deterministic for the same schema and generator version.
- Migrations are generated as drafts for developer review; Alembic/module migrations own actual schema changes and are never auto-applied.
- Keep Python behavior in extension classes; do not duplicate schema declarations in Python.
- Use typed Python model classes and descriptor fields so field paths can form query expressions, e.g. `Invoice.attachment.file_type == "pdf"` without a string parser.
- UUID IDs by default, generated in Python. Python names default to snake_case PostgreSQL columns; explicit table-name overrides are allowed.
- `created_at` / `updated_at` are explicit mixins with UTC-aware timestamps. Defaults distinguish Python defaults from database `server_default`.
- Enum storage defaults to text plus check constraint.
- Field validation runs before writes; PostgreSQL constraints remain the final integrity boundary.
- Built-ins planned: scalar/enum, URL (syntax and allowed scheme only; no network reachability check), JSON, FileReference (storage alias, key, metadata), and basic Location (latitude/longitude; optional description is application-owned). Validate coordinate ranges in Python and PostgreSQL.
- Composite fields are logical fields and need not map to JSON. Nested access is through the parent path; no implicit flattening aliases. Custom Field protocol is deferred beyond v1.
- Computed fields may be SQL-expression based or Python-computed. Input/output conversions are explicit converters and writes participate in the same transaction.

### Relationships and modules

- Relationship cardinalities: `one_to_one`, `many_to_one`, `one_to_many`, `many_to_many`; many-to-many uses an explicit junction model.
- One-to-one is guaranteed by a unique FK constraint. Delete behavior follows declared PostgreSQL FK policy; no hidden ORM cascade.
- Module registry is built from YAML manifests/model definitions in v1, then validated and frozen. Entry-point discovery/scaffold comes later.
- Module IDs/names are qualified (`module.Model`); public exports are explicit. Cross-module references require declared required/optional module dependencies and public exports.
- Required dependencies and version ranges are checked fail-fast. Dependency cycles are rejected. Definition registration has no DB/network side effects.
- Shared PostgreSQL schema with module-prefixed table names by default; explicit table overrides are allowed and collisions are validated.
- Each module owns Alembic migrations; KeelModel provides integration/metadata, not automatic schema mutation. Migration ordering follows dependency graph; migrations run explicitly, not at app startup.

### Query and projection

- Provide a model-aware query API over SQLAlchemy expressions; raw SQL is a separate database escape hatch with bind parameters and row/projection results, not model hydration.
- Common filters/operators, explicit order/pagination, default and maximum page size, `count()` and `exists()`; no query cache in core.
- Aggregate/group-by belongs to DataView, not ordinary Model queries.
- Projection sets are both reusable declarations and ad hoc selections, policy-filtered before SQL execution.
- V1 projection is root-model fields only. Nested relation paths are later; when added, only explicitly requested paths load, with permissions at every path and no implicit lazy I/O.
- Query operations unsupported by a source fail clearly; never silently ignore or Python-filter large result sets.
- Cursor pagination is preferred for DataViews, requiring a unique, non-null key; total count is not returned by default.

### Authorization

- KeelModel provides an authorization framework/contract, not concrete permission names, identities, login, roles, or policy definitions. Applications authenticate users and supply trusted context/evaluator.
- Permission names are module/application defined. Checks are action-specific and cover action, record scope, and per-field read/write.
- Evaluator is a pure synchronous function with no DB I/O; it receives context/action/resource/proposed values and returns field decisions plus SQLAlchemy row predicates. SDK applies predicates in the query/write transaction.
- Read: fields denied by policy are omitted from a typed partial projection; protected fields are not selected into process memory and cannot be filtered/sorted/aggregated by default.
- Write: each operation chooses `strict` or `omit`. Strict denial raises structured PermissionDenied. Omit updates only allowed fields; denied/missing fields are not included in UPDATE. If no fields remain, return no-op and do not audit. Bulk uses same semantics; strict failure rolls back entire atomic batch.
- Create policy receives proposed values before insert; denied fields are omitted and defaults/nullability apply, otherwise required-field validation fails.
- Row scope is embedded in UPDATE predicate. Zero matches do not distinguish nonexistent from out-of-scope records. No row lock by default; version checking is opt-in.
- Permission and business validation remain distinct. Denied-attempt logging is application-owned. Raw SQL/direct DB writes are outside KeelModel enforcement.

### Transactions and writes

- SDK opens a transaction for a standalone operation; callers may supply/reuse a transaction to compose work atomically.
- Create requires required fields/defaults; Update is PATCH: absent fields remain unchanged, explicit null is separate, and field-level permissions are enforced.
- Bulk operations are atomic by default. Both set-based and per-record patches are needed; typed `RETURNING` is supported. Audit only actual changed values.
- Last-write-wins is the default. Optimistic version checks are opt-in for operations that require conflict detection.
- Structured error classes are transport-neutral.
- Idempotency keys are optional at write boundaries, not required for every mutation.

### Audit (optional `keelmodel-audit` package)

- Model opt-in via `audit=True`; audit is a capability, not a mandatory domain rule.
- Audit mutations only, per record, in the same PostgreSQL transaction as data. Append-only via SDK; application owns retention/purge.
- Store entity/action, opaque actor type/id, correlation and batch IDs, database timestamp, and JSON before/after diffs for changed fields. No-op writes create no audit entry.
- Field metadata controls audit inclusion/redaction. Permission-omitted fields do not appear in audit.
- Hard-delete audit preserves entity identity and redacted before-diff, not a full snapshot. Soft-delete/restore have distinct actions.
- `get_audit` is protected by the permission evaluator; cursor pagination newest-first.

### Soft delete (later phase)

- Soft delete is opt-in per model and uses nullable `deleted_at`; null means active and timestamp means deleted. Restore has an explicit API.
- Queries exclude deleted roots/collection items by default; `include_deleted` is explicit per query/path. To-one references to soft-deleted records remain visible for historical integrity.
- FK references remain; soft delete does not cascade or block by default. Hard delete is explicit with a separate permission and PostgreSQL FK constraints decide validity.
- Active-only uniqueness uses PostgreSQL partial unique indexes represented in metadata and applied through module Alembic migrations. Restore conflicting with an active unique key fails with structured conflict.
- Bulk soft delete is atomic with per-record audit.

### DataView (later phase)

- DataView is a read-only projection model with declared output fields and source; not necessarily a PostgreSQL VIEW.
- Sources planned: SQLAlchemy SELECT expressions and mapped existing PostgreSQL views. DataView composition may join models and other DataViews only within the same PostgreSQL query context; no federation.
- Cross-module DataView references require declared module dependency/public export. Registry validates dependency graph/cycles.
- Common filter/sort/pagination contract over declared fields, unique non-null key, typed projection result, clear errors for unsupported operations.
- Aggregates/group-by are DataView capabilities. Soft-deleted Model sources are excluded by default, explicit inclusion may be declared.
- DataView is deferred from v1; basic SQLAlchemy SELECT is the initial later phase, native view mapping/composition after foundational behavior is proven.

### Outbox/search and lifecycle

- External effects follow state-first: commit business state plus explicit outbox event in one DB transaction, then process externally. Never hold DB transaction open during HTTP calls.
- Outbox is optional package/contract; v1 scope is later. Event is explicit from application/domain service, not inferred from every CRUD update.
- Event payload is entity reference plus aggregate version; worker treats it as a latest-state refresh signal, allowing coalescing, not exact historical snapshot replay.
- Optional polling worker uses PostgreSQL row locks (`FOR UPDATE SKIP LOCKED`) and leases; at-least-once delivery, stable event IDs, retries. Failed events are retained for inspection/retry; successful events retained then purged by app-owned policy. Basic metrics expose backlog, age, failures, attempts, last error.
- Projection package owns Elasticsearch mapping, indexing and rebuild. KeelModel does not ship Elasticsearch integration in core.
- No generic `OnUpdate`/UI/ViewTree event bus. Hooks, if later added, are technical/validation-only; no mutation transforms, no non-durable after-commit callback. Business logic stays explicit in application services; durable side effects use outbox.

## V1 Boundary (provisional)

- PostgreSQL + SQLAlchemy async path; sync API is a later separate path despite being a desired capability.
- Typed models, descriptors, fields/relations, query/projection on root model, transaction/bulk, full permission contract and enforcement.
- Built-ins: scalar/enum, URL, JSON, FileReference, Location.
- Explicit module registration; Alembic integration.
- Optional audit package is required only for apps that enable audit.
- DataView, soft delete, entry-point discovery/scaffold, outbox worker/search, sync API and public custom Field protocol are later phases.
- No REST/GraphQL/admin UI/auth/login/workflow/federation.

## Trade-offs and Risks

| Item | Impact | Response |
|---|---|---|
| Full field + row authorization in v1 | high | Keep evaluator pure and SQL-based; enforce before reads and within writes; integration-test adversarial cases. |
| Async first, sync later | medium | Share model metadata/contracts; do not promise sync support until its independent path is tested. |
| Cross-module model ownership | medium | Qualified public references and explicit dependency graph; reject cycles. |
| Many selected features risk a heavy framework | high | Preserve phased boundary and resist adding transport, UI, workflow, or federation. |
| Entity-reference outbox can skip intermediate states | medium | Treat as latest-state refresh only; use explicit snapshot/domain event if exact replay later becomes required. |
| Field-level omission makes projection partial | medium | Use typed partial record with presence tracking rather than silently setting denied fields to null. |

## Assumptions and Open Questions

- Repository/product naming is KeelModel; prior typo “QModel” refers to KeelModel.
- Exact public API/class names are intentionally not fixed.
- Sync API desired after async-first release; release boundary remains subject to implementation estimate.
- DataView native mapping/composition, soft delete, outbox worker, entry points, and custom field protocol are deferred.
- **Falsifying signal:** a target app cannot implement a representative ERP module without reaching through KeelModel internals or adding multiple overlapping abstractions.

## Security Considerations

The application owns authentication and concrete authorization policies. Context/evaluator must be trusted and supplied by backend code, never accepted as unverified frontend claims. KeelModel enforces only SDK-supported paths; direct SQL is outside its protection. Read policies must restrict SQL selection and query use, not only response serialization. Audit data is sensitive and requires field redaction and application-owned retention.

## Revisit Trigger

Revisit scope if real ERP module implementation requires DataView, soft delete, sync access, or outbox earlier than planned, or if the evaluator contract cannot express required policies without DB I/O.

## Next Step

Continue product discussion. When requested, convert this brainstorm into an evidence-based implementation plan and validate the provisional v1 boundary against a representative module.
