---
status: proposed
last_reviewed: 2026-11-22
superseded_by: []
related_code: []
---

# Discovery: KeelModel Implementation

## Outcome and Scope
- Desired behavior: deliver a strict, sync-first Python data SDK for ERP/business applications, with YAML as the source of truth for model schema and authorization policy.
- Users: application/module developers.
- Non-goals: ERP application, auth/login/user store, HTTP API, UI, workflow engine, hidden hooks, async API in the first core release, multiple database backends, automatic migration application.

## Evidence
- [Current scope](../20261122-keelmodel-scope/brainstorm.md) — current product decisions.
- [Prior design](../20261121-keelmodel-design/brainstorm.md) — broader earlier proposal; newer scope takes precedence.
- [AGENTS.md](../../AGENTS.md), [docs/WORKFLOW.md](../../docs/WORKFLOW.md) — repository rules.
- Repository has no Python package, implementation, or test suite. Git is initialized; existing working files are untracked and must be preserved.

## Existing Contracts and Patterns
- No implementation/API/test patterns yet. Product contracts must be designed before code.
- Project includes harness/docs/history files; do not replace unrelated state.

## Constraints
- Technical: PostgreSQL + SQLAlchemy, synchronous Python SDK first; generated Python is deterministic, committed output, never hand-edited.
- Operations: Alembic migration drafts only; explicit module registration, no auto-discovery.
- Security/data: authorization defaults to deny; deny overrides allow. Core owns action/record and trusted-role matching. Optional field authorization extension must enforce inside DB operations; raw SQL/direct ORM is outside SDK protection. Audit is optional extension, same transaction, retention owned by application.

## Facts, Assumptions, Questions
- Verified at start: no package or tests existed. Current implementation now includes uv package foundation, strict initial model YAML parser/generator, module manifest parsing/registration, and SQLAlchemy model mapping.
- Confirmed: schema persistence core, CRUD + atomic bulk, explicit modules, action/record + role matching in auth core, optional field authorization extension, optional audit extension, Alembic drafts.
- Confirmed this planning turn: default deny; denied read fields are omitted; writes containing denied fields reject the whole operation; bulk is atomic; core first, extensions after core contracts prove stable.
- Assumed: core release includes schema generation, module/data API, migrations, keelpolicy core action/record checks. Audit and field/role extension follow as optional packages in the same project.
- Open for technical design: exact YAML grammar/operand typing, partial-read result contract, role context shape, bulk result behavior, precise field type options, generator/toolchain, extension boundary/API and audit record contract.

## Clarifications
- 2026-11-22: synchronous-only SDK first; not HTTP API.
- 2026-11-22: application owns authorization YAML and passes typed subject plus trusted attributes; keelpolicy is a sibling Python package in this repository, independent of SQLAlchemy/PostgreSQL; KeelModel may depend on it, not the reverse. Evaluation returns decision plus neutral condition AST for KeelModel to translate.
- 2026-11-22: field-denied reads omit fields; writes with any denied field reject as a whole; bulk is atomic. Role matching is core; field-level authorization is optional.
