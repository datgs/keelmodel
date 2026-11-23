---
status: proposed
last_reviewed: 2026-11-22
superseded_by: []
related_code: []
---

# Approach: KeelModel Implementation

## Recommendation

Implement from public contracts inward, in gated phases. First write a technical design that narrows scope and defines model YAML, policy YAML, module registration, synchronous data/unit-of-work operations, transaction/bulk behavior, and extension contracts. Then deliver a usable core. Add optional field/role authorization and audit after core transaction and policy contracts are proven. Keep keelpolicy inside this project with a distinct internal package boundary.

Execution remains explicit: parse/validate declarations, generate models, register modules, create a session/transaction, check authorization, execute database operation, return typed result/error. No implicit hooks or auto-discovery.

## Meaningful Alternatives
- Ship core and all extensions together — faster feature completeness, but forces unproven extension contracts into first release and raises security/test scope.
- Implement direct SQLAlchemy mapping without KeelModel query/write contracts — simpler, but does not deliver consistent authorization/transaction behavior.

## Contracts and Integration
- Inputs: module-owned model YAML and application-owned policy YAML; application passes a typed subject plus trusted attributes.
- Outputs: deterministic generated Python models; explicit module registry; sync data operations; reviewable Alembic drafts; structured errors.
- Authorization: default deny; deny-overrides; core checks action and record access, including trusted role selectors. keelpolicy returns a decision plus neutral condition AST; KeelModel translates it to SQL. Field-level checks are optional and fail configuration if policy requests unsupported capability. Denied read fields are omitted; writes with any denied field fail atomically.
- Audit: optional package, same transaction as data mutation; application controls retention.
- Compatibility: version model and policy YAML; no promise of cross-database behavior or async SDK in core release.

## Risk and Evidence
| Area | Risk | Evidence or validation |
|---|---|---|
| Public YAML/API contracts | high | No existing code; define fixtures and compatibility rules before implementation. |
| Authorization correctness | high | Default-deny and deny-overrides confirmed; integration tests for every supported path; security review recommended. |
| Partial reads | high | Omitted fields require explicit presence-aware result contract; denied is not null. |
| Bulk writes | high | Whole-operation rejection on denied field; define atomicity, per-record decisions and return semantics before implementation. |
| Extensions/audit transactions | high | Add after core transaction API; prove rollback includes audit entry. |
| Scope creep | high | Keep DataView, soft delete, custom field protocol, async, search/outbox worker, identity management, UI/workflow out. |

## Migration, Operations, and Rollback
- Migration: Alembic drafts only; module/application own revision history and explicit application. Never auto-apply at startup.
- Observability: structured errors and explicit policy/config validation diagnostics; no worker/metrics subsystem.
- Rollback: no persisted user data exists yet; version public schemas and use Alembic explicit reversible migrations where applicable. Generated output is reproducible from committed YAML/tool version.

## Accepted Assumptions
- Initial core targets PostgreSQL and sync Python API.
- `keelmodel` and `keelpolicy` are sibling Python packages in this repository; KeelModel may depend on KeelPolicy, not the reverse. Independent repository/distribution deferred.
- Composite fields are deferred. FileReference and Location are typed JSONB values; no storage/network/GIS services are implied. Generated models are application/module-owned; common scalar set, core relations, structured check expressions, URL syntax/scheme validation, limit/offset pagination, and explicit UUID/timestamp mixins are documented in the contract spec.
- Recommend hd-security-review plan-review before implementation; not yet run or approved.
