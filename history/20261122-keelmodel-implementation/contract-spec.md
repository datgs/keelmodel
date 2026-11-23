---
status: proposed
last_reviewed: 2026-11-22
superseded_by: []
related_code: []
---

# KeelModel v1 Contract Spec

This is the concise public-contract draft for implementation. `MUST` statements are accepted decisions; `PROPOSED` items need confirmation in technical design before they become compatibility promises.

## 1. Product boundary

- KeelModel is a synchronous Python data SDK, PostgreSQL-first, implemented with SQLAlchemy beneath its public contracts.
- The application owns business services, authentication, trusted actor context, and authorization policy YAML.
- `keelpolicy` is an internal library in this project. It validates and evaluates policy; it does not manage users, credentials, sessions, role assignment, or persistence.
- YAML is the source of truth for model and policy declarations. Generated Python and parsed policy objects are derived artifacts, never separately edited sources.
- Module loading, extension enablement, transactions, and migrations are explicit. No implicit hooks or auto-discovery.
- Raw SQL and direct SQLAlchemy access are outside KeelModel authorization guarantees.

## 2. Model schema YAML

One strict, versioned file per model. Unknown keys and unsupported types MUST fail validation before generation.

```yaml
version: 1
module: sales
model: Invoice
table: sales_invoice

fields:
  id:
    type: uuid
    primary_key: true
    default: uuid4
  customer_name:
    type: text
    required: true
  status:
    type: enum
    values: [draft, submitted, approved, cancelled]
    storage: text
  total:
    type: decimal
    required: true
  created_by:
    type: uuid

relations:
  customer:
    type: many_to_one
    target: customer.Customer
    required: true

constraints:
  unique:
    - [customer_id, status]
```

- Canonical resource name: `<module>.<Model>`; table name is explicit or derived by one documented deterministic naming rule.
- YAML owns fields, relations, and constraints. Python extension classes, if used, add behavior only and cannot add schema.
- Generated Python is deterministic, committed under a dedicated generated path, never hand-edited; CI regeneration drift is a failure.
- v1 scalar types: UUID, text, integer, decimal, boolean, date, timezone-aware datetime, and bytes; also enum, JSON, URL, FileReference, and Location. Composite fields are deferred.
- FileReference and Location are typed values stored as JSONB; neither implies storage/upload or GIS integration.
- URL validation checks syntax and allowed scheme; no network checks.
- Relations: many-to-one, one-to-one, one-to-many; many-to-many uses an explicit junction model. One-to-one is enforced with a unique foreign key. Constraints: primary key, foreign key, unique, and structured check.
- Check expressions support field/literal equality, inequality and order comparisons, null checks, and `all`/`any`; no arithmetic, SQL strings, or custom Python.
- Generated Python is written to an application/module-owned path, not inside the SDK package.
- UUID identifiers and timestamp fields are explicit named mixins; no implicit columns are added to a model.
- **PROPOSED before freeze:** exact type options, defaults/nullability, relation key naming, expression operand typing, allowed URL schemes, Location JSON shape, naming rule, mixin syntax.

## 3. Module manifest and registration

```yaml
version: 1
name: sales
module_version: 1.0.0
requires:
  - name: customer
    version: ">=1.2,<2.0"
exports:
  models: [Invoice]
```

- Modules are installed Python packages and are registered explicitly by the application.
- Registration validates unique names, versions/dependencies, dependency cycles, public exports, cross-module references, and table/resource collisions.
- Only exported models can be referenced from another module.
- Registration performs no database/network operation.
- **PROPOSED before freeze:** whether manifest model paths are fixed by convention or configurable; exact version-range grammar and dependency error policy.

## 4. Python SDK surface

Illustrative names; exact spelling is **PROPOSED**, while synchronous operation and semantics below are accepted.

```python
sdk = KeelModel(registry=registry, engine=engine, policy=policy)

with sdk.transaction(context=trusted_context) as tx:
    invoice = tx.read(Invoice, invoice_id, fields=[Invoice.id, Invoice.total])
    tx.create(Invoice, values={...})
    tx.update(Invoice, invoice_id, patch={...})
    tx.delete(Invoice, invoice_id)
    tx.query(Invoice).where(Invoice.status == "draft").limit(100).all()
    tx.create_many(Invoice, values=[...])
    tx.update_many(Invoice, patches=[...])
    tx.delete_many(Invoice, ids=[...])
```

- A standalone operation may own a transaction; callers can explicitly compose operations in one transaction.
- Query supports typed field expressions, filters, ordering, and bounded limit/offset pagination. Maximum page size is configurable; exact method names are **PROPOSED**.
- For field-protected data, read, filter, and order are separate capabilities; policy must explicitly grant filter/order separately from read.
- Field write permissions distinguish create from update.
- Bulk is atomic: one denied record/field or hard validation/persistence failure rolls back the full batch.
- Writes with any denied submitted field fail as a whole.
- Errors are structured and transport-neutral: validation/schema/configuration, registry, permission denied, not found, conflict, persistence. Exact inheritance/names are **PROPOSED**.
- UUID default, timestamp mixins, enum text/check behavior, and precise create/update/delete return semantics require final schema/API contract review.

## 5. Policy YAML and authorization

Application-owned, strict, versioned YAML. `keelpolicy` validates/evaluates rules; KeelModel applies decisions to supported database operations.

```yaml
version: 1
default: deny

policies:
  - name: read-own-invoices
    effect: allow
    roles: [sales_clerk]
    resource: sales.Invoice
    actions: [read]
    record:
      all:
        - field: created_by
          equals_context: actor_id
```

- No matching allow means deny. Matching deny overrides allow.
- Application passes trusted actor/context; roles are claims supplied by the application, not stored or assigned by KeelModel.
- Core checks action and record access, including matching trusted roles in policy selectors. Record conditions MUST constrain the database operation; they are not post-fetch filters.
- Field-level enforcement is an optional extension; policies using field-level rules require the extension explicitly.
- Roles are supplied by the application; `keelpolicy` does not assign, store, inherit, or authenticate roles. Core matches trusted roles for action/record rules.
- Initial condition operators: equality/inequality, ordered comparisons for compatible scalar types, membership, null check, and `all`/`any` groups; custom functions and arbitrary expressions are excluded.
- Application supplies a typed subject (identity and trusted roles) plus a separate trusted attributes map; `keelpolicy` defines the input contract and does not construct/authenticate subjects.
- Policy evaluation returns a decision plus a neutral validated condition AST when record scoping is needed. KeelModel validates model field references and translates that AST to SQL; `keelpolicy` returns no SQLAlchemy expression.
- **PROPOSED before freeze:** exact subject/resource/action vocabulary, attribute value types, operand typing/grammar, how policy is loaded/compiled, and behavior for invalid/ambiguous conditions.

## 6. Optional field/role authorization extension

- Explicit opt-in capability within the same project; not required by applications that do not use field-level rules.
- If policy includes field-level rules and the extension is absent, initialization/validation MUST fail clearly.
- Denied read fields are omitted from a typed partial result and MUST NOT be selected into application memory.
- Any denied submitted write field rejects the entire write/bulk operation.
- Read, filter, and order are separate field capabilities. A field cannot be filtered or ordered unless policy explicitly grants that operation, even if it can be read.
- Create and update write access are separate field capabilities.
- Extension is a narrow authorization capability, not a general plugin/hook framework.

## 7. Optional audit extension

- Optional package/capability within the same project; explicitly enabled per application/model.
- Mutation audit is written in the same database transaction as the business mutation; rollback affects both.
- Audit is append-only through SDK APIs. Application owns retention/purge.
- Redaction, actor/correlation fields, hard-delete shape, and audit read authorization are **PROPOSED before freeze** and must be decided before implementing the extension.

## 8. Migrations

- SQLAlchemy metadata integrates with Alembic.
- KeelModel may generate draft revisions for review; it MUST NOT auto-apply migrations at startup or registration.
- Modules/application own revision history and explicitly apply migrations.
- Exact generator UX and per-module Alembic layout are **PROPOSED before freeze**.

## 9. Generation/package layout

Use the accepted repository layout in [structure.md](structure.md). `keelmodel` and `keelpolicy` are sibling Python packages under `src/` in the same repository; KeelModel may depend on KeelPolicy, not the reverse. SDK source, tests, examples, and generated application-owned output remain separate.

The directory tree guides ownership; do not split cohesive code into extra files merely to match the tree.

## Acceptance rules

1. Invalid/unknown YAML fails with source location and useful diagnostic; no silent fallback.
2. Generating twice from identical inputs/tool version produces byte-identical output; drift check detects edits.
3. Module registration rejects undeclared/private cross-module references and dependency cycles.
4. Default deny and deny-overrides are verified with positive and negative tests; core matches trusted roles for action/record rules.
5. Record restrictions are in SQL predicates for every supported read/write path.
6. Read-denied fields never enter returned objects; write-denied fields reject the whole atomic operation.
7. Optional extension use is explicit; missing required extension fails closed.
8. Audit and business mutation commit/rollback together.
9. Migration generation produces a reviewable draft and never changes the database.

## Status and next gate

The main product boundaries and denial/atomicity semantics above reflect user decisions. The first implementation pass has begun; remaining items marked **PROPOSED before freeze** are not yet compatibility promises. Authorization enforcement is gated on security review.
