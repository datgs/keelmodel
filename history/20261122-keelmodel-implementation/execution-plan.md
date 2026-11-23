---
status: proposed
last_reviewed: 2026-11-22
superseded_by: []
related_code: []
---

# Execution Plan: KeelModel Core and Optional Extensions

Team: single-owner until execution approved
Path: High-risk (public schema/API contracts, authorization, migrations, audit data)

## Outcome and Approach

Deliver a strict, sync-first Python data SDK for ERP/business applications. YAML is the source of truth for model and authorization declarations. Core provides generated models, explicit module composition, PostgreSQL data operations, action/record authorization through the in-project keelpolicy, and reviewed Alembic drafts. Optional field/role authorization and audit follow after core contracts are proven. See [discovery.md](discovery.md) and [approach.md](approach.md).

## Tasks

| # | Task | Blocked by | Ownership | Output contract |
|---|---|---|---|---|
| 0 | Technical design and scope gate | User plan approval | Product/API contracts | Versioned model/policy YAML schemas, SDK/module/transaction/error contracts, supported field/operator list, extension interfaces, acceptance fixtures, explicit exclusions. |
| 1 | Project/package/tooling foundation | 0 | Root packaging, CI, tests | Installable package; reproducible toolchain; formatting/lint/type/test commands; CI validation. Preserve existing harness/docs/history. |
| 2 | Model YAML validator and deterministic generator | 1 | Model schema/compiler/generation | Strict versioned YAML; UUID/text/integer/decimal/boolean/date/timezone-aware datetime/bytes plus enum/JSON/URL/FileReference(JSONB)/Location(JSONB); no composites; structured basic check constraints; generated Python to app/module-owned path; clear diagnostics, deterministic output, drift check and negative fixtures. |
| 3 | Model runtime and PostgreSQL metadata | 2 | Generated/runtime model mapping | Typed generated models map to SQLAlchemy/PostgreSQL; constraints/defaults/relations match declarations; generated files not hand-edited. |
| 4 | Explicit module composition | 3 | Manifest/registration | Validate module identity, versions/dependencies, public exports, reference visibility and collisions; no source scan or DB side effects. |
| 5 | Sync session, transaction, and basic data API | 3, 4 | Data API/unit-of-work | CRUD/query, explicit transaction reuse, structured errors and bounded pagination on one clear transaction contract. |
| 6 | Bulk operations | 5 | Bulk API | Atomic bulk behavior and typed results; denied submitted field rejects whole operation/batch; rollback integration tests. |
| 7 | Alembic integration and migration drafts | 3, 4 | Migration tooling | Metadata integration and reviewable draft generation; module-owned revisions; never auto-apply; sample diff inspection. |
| 8 | keelpolicy core | 0, 1 | Sibling package under src/keelpolicy | Strict versioned policy YAML validation/evaluation; typed subject + trusted attributes; core role selectors; default deny, deny-overrides, action/resource/record conditions; basic comparisons/membership/null/all/any. Returns decision + neutral condition AST; no ORM/DB, identity store, custom functions or implicit merge. |
| 9 | Core authorization integration | 5, 8 | Data API/query/write boundary | Enforce action and record predicates on all supported SDK paths; raw SQL/direct ORM explicitly unprotected. |
| 10 | Core security verification | 6, 7, 9 | Security tests/docs | Positive/negative tests for default deny, conflicts, record isolation, denied writes, bulk atomicity, policy validation and bypass boundaries. Run hd-security-review plan-review before execution. |
| 11 | Representative module and core acceptance | 2-10 | Example/acceptance suite | One small business module demonstrates YAML-to-model, registration, CRUD/transaction, migration draft and action/record policy without internal escape hatches. |
| 12 | Optional field authorization extension | 11 | Optional capability + SDK adapter | Explicit opt-in; field read/create/update/filter/order rules consume trusted context/roles; denied reads omit fields without selecting protected values; denied-field write rejects whole operation; missing extension with such rules fails clearly. Test query and bulk paths. |
| 13 | Optional audit extension | 11 | Audit package + transaction adapter | Mutation audit in same transaction; rollback parity; redaction/exclusions and append-only SDK path; audit query contract; application-owned retention. |
| 14 | Documentation and release boundary | 10-13 | Public docs/examples/release checks | Core vs optional capabilities, security exclusions, YAML examples/versioning, migration workflow, sync-only status, reproducible install/test instructions. |

## Execution Guidance
- Critical path: 0 → 1 → 2 → 3 → 4 → 5 → 9 → 10 → 11.
- keelpolicy task 8 may proceed after task 0/1 in parallel only if contract fixtures are frozen and package ownership is separate.
- Migration drafts (7) depend on model metadata/module ownership; never run against shared/production databases in development.
- Optional extensions (12, 13) start only after core acceptance (11); parallel work requires separate ownership and frozen transaction/policy contracts.
- Generated files, YAML schemas, exports, CI and migration metadata are shared hubs; use one integration owner.
- No Python package or tests exist yet. Select toolchain in task 0/1 and record exact commands; do not claim validation before it exists.

## Verification Strategy
- Task checks: schema positive/negative fixtures; deterministic regeneration diff; model/DB metadata tests; module dependency/collision tests; sync CRUD/transaction/bulk integration against isolated PostgreSQL; Alembic draft inspection without auto-apply; policy evaluator unit tests.
- Security integration: prove unauthorized records/fields do not cross supported SDK boundary; test bulk paths, conflicts, missing rules/extension, rollback. Document raw SQL bypass as outside protection.
- Extension integration: audit and business mutation commit/rollback together; field restrictions enforced in query/write path; denied field write rejects entire mutation.
- Final acceptance: run toolchain checks established in task 1 and representative module end-to-end against isolated database.
- No exact verification commands exist in this repository yet.

## Risks and Approval
- Confirmed: sync SDK first; PostgreSQL only; default deny; deny-overrides; denied read fields omitted; any denied write field rejects whole operation; bulk atomic; core first, optional extensions later; keelpolicy stays in this project; roles are matched by core; composite fields deferred; FileReference and Location use typed JSONB values; protected field read/filter/order are separate grants; create/update field writes are separate; one-to-one uses unique FK; common scalar set includes UUID/text/integer/decimal/boolean/date/timezone-aware datetime/bytes; URL syntax+scheme validation; structured basic checks; app/module-owned generated output; limit/offset pagination; explicit mixins for UUID/timestamps.
- Open risks: exact YAML grammar/operand typing; partial result typing; module version rules; precise field type options and naming; trusted context shape; bulk result shape; audit contents/redaction; policy runtime compilation.
- Approval: user approved implementation of v1 foundation. Begin package/tooling and model-schema work. Authorization enforcement remains gated on security review; review tooling is unavailable in this environment, so do not implement enforcement until review can be completed.

## Live Plan Rule

Workers submit evidence-backed plan-change proposals if implementation constraints invalidate a contract. Review scope, dependency and security impact before continuing; material policy changes return to user for approval.
