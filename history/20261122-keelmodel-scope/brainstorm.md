---
status: proposed
last_reviewed: 2026-11-22
superseded_by: []
related_code: []
---

# Brainstorm: KeelModel Scope and KeelPolicy

## Decision

- **Recommendation:** Keep KeelModel a strict, lightweight Python data SDK for business/ERP applications. YAML is the single source of truth for declarative model and authorization policy. Keep runtime behavior explicit and linear, with no unnecessary abstraction layers or hidden hooks. `keelpolicy` is part of the KeelModel project for now, not a separate project/repository.
- **Decision owner:** User
- **Confidence:** medium — product direction was confirmed in discussion, but no technical design, implementation, or workload validation exists.

## Problem and Outcome

Provide shared, reliable data-layer contracts that save business applications from repeating costly or error-prone persistence behavior, without taking over application-specific services, business rules, or policy ownership. Applications may vary in configuration while using consistent data operations.

## Constraints and Non-Goals

- PostgreSQL-first; SQLAlchemy is persistence implementation beneath KeelModel's public contracts.
- Python SDK synchronous API first. This means Python `def` APIs, not HTTP endpoints.
- YAML is strict, versioned, and authoritative. Generated Python is deterministic output, committed separately, never hand-edited, and checked for drift.
- Keep abstractions to one or two clear layers; prefer explicit registration and linear execution.
- No full ERP, login/authentication, HTTP API, admin UI, workflow engine, generic event system, or cross-database federation.
- Application owns use cases, services, business rules, authentication, trusted actor context, and policy YAML.
- Raw SQL/direct SQLAlchemy access is outside KeelModel authorization enforcement unless an explicit future contract changes this.

## Evidence

- Product owner confirmed the design principles and scope decisions in discussion on 2026-11-22.
- Prior design brief `history/20261121-keelmodel-design/brainstorm.md` contains earlier broader proposals; this document records the newer scope discussion and supersedes conflicting assumptions once accepted.
- No implementation or runtime behavior has been validated.

## Confirmed Direction

### KeelModel

- YAML model schema is the single source for persistence fields, relations, and constraints.
- Generated Python models are runtime-facing output; Python extensions add behavior only, not duplicate schema.
- Explicit module registration and declared dependencies/public exports; no automatic entry-point discovery in the initial scope.
- Initial data API includes CRUD and bulk operations.
- Alembic migration drafts may be generated for review; modules/application own migration revisions and explicitly apply them.
- Sync Python SDK first; async is not part of initial API.
- v1 field types include scalar, enum, JSON, URL, FileReference, and Location; composite fields are deferred. FileReference is a typed JSONB value with no upload/storage integration. URL checks syntax/scheme only; Location does not imply GIS.
- Audit is included in the first delivery as an optional extension/package, not mandatory core behavior. Audit mutations in the same transaction; application owns retention/purge.

### Authorization and KeelPolicy

- User wants a separately named policy library, provisionally `keelpolicy`, using YAML as policy single source of truth, similar in style to AWS policy documents but not claiming AWS IAM schema or semantic compatibility.
- `keelpolicy` scope: policy structure, validation, and evaluation for subjects/roles, permissions, actions, resources, and basic conditions. It does not own authentication, user storage, sessions, or role assignment.
- Application owns policy YAML and supplies trusted actor/context. Modules expose resource/action contracts and do not implicitly merge policy defaults.
- KeelModel integrates authorization into database operations. Record conditions must constrain SQL reads/writes; SQL predicate translation is KeelModel integration, not a generic responsibility of the policy library.
- Core authorization includes action-level and record-level checks and matches trusted roles in policy selectors. Application supplies roles; KeelModel does not assign, store, or inherit them.
- Field-level read/write is an optional extension. When enabled, enforcement must occur in query/write paths, not only after fetching rows. A policy declaring field rules without the extension must fail clearly, never silently ignore them.
- Initial conditions use equality/inequality, compatible ordered comparisons, membership, null check, and `all`/`any`; exact operand typing/grammar remains open. No custom application functions/hooks.
- Default deny and deny-overrides are confirmed. Denied read fields are omitted from typed partial results; any denied submitted write field rejects the whole operation. Bulk writes are atomic.
- A conceptual class diagram was discussed: Application owns/loads policy and supplies context; KeelModel always invokes core authorization; an optional field extension is used explicitly by KeelModel. This is not a finalized class/API design.
- `keelpolicy` is an internal library/package within this KeelModel project; do not split it into a separate project/repository now. A separate independently published distribution is not currently required.

### Illustrative Policy YAML (not a finalized schema)

```yaml
apiVersion: keelpolicy/v1
default: deny

roles:
  sales_clerk: {}
  sales_manager: {}

policies:
  - name: clerk-read-own-invoices
    roles: [sales_clerk]
    resource: sales.Invoice
    actions: [read]
    effect: allow
    record:
      all:
        - field: created_by
          equals_context: actor_id
    fields:
      read:
        allow: [id, customer_name, status, total, created_at]
        deny: [internal_note]

  - name: clerk-update-own-invoices
    roles: [sales_clerk]
    resource: sales.Invoice
    actions: [update]
    effect: allow
    record:
      all:
        - field: created_by
          equals_context: actor_id
    fields:
      write:
        allow: [customer_name]
        deny: [status, total, internal_note]

  - name: manager-read-all-invoices
    roles: [sales_manager]
    resource: sales.Invoice
    actions: [read]
    effect: allow
```

The YAML is an example for discussion only. Field-denied reads are omitted; denied writes reject the whole operation.

## Provisional Initial Scope

- Strict YAML schema validation and deterministic Python generation/drift check.
- PostgreSQL-backed synchronous SDK with model registration, CRUD/query, transactions, and bulk operations.
- Explicit module contracts and Alembic draft integration.
- Core action/record authorization, with application-owned policy YAML and trusted context.
- Optional field authorization extension and optional audit package follow after the core contract is proven.
- Keep excluded unless concrete application evidence warrants them: soft delete, DataView, generic custom Field protocol, outbox worker/search, automatic module discovery/scaffold, sync+async dual API, transport/UI/authentication/workflow, and abstract plugin/hook pipelines.

This scope is provisional and broad; validate each capability against a representative application before treating the list as a committed v1 contract.

## Meaningful Alternatives

### Keep `keelpolicy` within the KeelModel project

- **Selected for now:** Preserve a distinct policy-library boundary and name, but keep it in this project/repository. This avoids premature project and release separation while allowing a clear internal contract.
- **Revisit when:** A real independent consumer or release need makes separate distribution valuable.

## Trade-offs and Risks

| Item | Impact | Response |
|---|---|---|
| YAML model and policy contracts are public and versioned | high | Strict validation, compatibility policy, positive and negative tests before release. |
| Authorization enforcement is security-sensitive | high | Test every supported read/write/bulk path; fail closed; clearly exclude raw SQL/direct ORM paths. Recommend security plan review before implementation. |
| Optional field extension can be misconfigured | high | Explicit enablement and startup/configuration error if policy uses unsupported field rules. |
| CRUD + bulk + audit + multiple field types create a large initial scope | high | Stage implementation by contracts; validate necessity using a representative module; reject speculative extras. |
| Separate `keelpolicy` project/distribution could add overhead | low for current scope | Keep it inside the KeelModel project; reconsider only with a proven independent consumer or release need. |
| YAML DSL may grow into an opaque programming language | high | Limit initial conditions/operators; no custom functions, inheritance, implicit merge, or hook pipeline. |
| Sync-first may not fit async-only consumers | medium | Deliver one tested execution path; revisit async only with workload/consumer evidence. |

## Assumptions and Open Questions

- Exact scalar types/options, defaults/nullability semantics, relation key naming, structured check grammar, URL validation, Location storage shape, and naming rule.
- Exact policy subject/resource/action vocabulary, context shape, operand typing, and policy YAML grammar.
- For protected fields, read/filter/order are separate capabilities; exact policy YAML shape remains open.
- Audit payload/redaction/actor fields and Alembic draft UX/layout remain open.
- Does each module publish resource/action names and field metadata, while application alone owns allow/deny policy?
- **Falsifying signal:** a representative application needs many escape hatches, reaches into SQLAlchemy internals for normal use, or cannot express its policy without a growing custom DSL.

## Security Considerations

Application-supplied actor/context must be trusted backend data, not client-provided claims without verification. Core and optional extension enforcement must occur before data leaves the database boundary. Raw SQL/direct database writes are not covered by SDK policy enforcement. Audit content is sensitive and needs redaction and application-owned retention.

## Revisit Trigger

Revisit whether to publish `keelpolicy` separately only if a second non-KeelModel consumer or release need appears. Revisit authorization scope if common policies require custom functions, role inheritance, or cross-resource joins; revisit field extension semantics based on a representative application's read/write needs.

## Next Step

The project boundary for `keelpolicy` is now decided: keep it within KeelModel. Before technical design, close default-deny and field-denial semantics, then validate provisional scope against one representative ERP module. Create an implementation plan only when the user asks to move into planning.
