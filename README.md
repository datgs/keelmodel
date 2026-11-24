# keelmodel

[![PyPI](https://img.shields.io/pypi/v/keelmodel)](https://pypi.org/project/keelmodel/)
[![Python](https://img.shields.io/pypi/pyversions/keelmodel)](https://pypi.org/project/keelmodel/)
[![CI](https://github.com/datgs/keelmodel/actions/workflows/ci.yml/badge.svg)](https://github.com/datgs/keelmodel/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A lightweight **pre-ERP framework**: declare business models in strict YAML,
get typed Python classes, a synchronous data SDK, and YAML-declared
authorization — over PostgreSQL, MySQL, or SQLite.

```bash
pip install keelmodel
```

```yaml
# models/invoice.yaml
version: 1
module: sales
model: Invoice
mixins: [uuid_pk, timestamps]
fields:
  number: {type: text, required: true, length: 40}
  total:  {type: decimal, required: true, default: 0}
relations:
  customer: {type: many_to_one, target: sales.Customer, required: true}
```

```python
km = KeelModel("postgresql://app:secret@db/shop", registry, authz=authz)
page = km.query("sales.Invoice", ctx,
                filters={"field": "total", "op": "gte", "value": 0})
```

## What you get

- **One source of truth.** YAML owns fields, relations, constraints, and
  mixins — no schema drift between code and migrations.
- **Sync, typed SDK.** `create / get / update / delete / query / bulk` with
  atomic bulk writes, typed errors, and limit/offset paging.
- **Multi-dialect.** Same model code runs on PostgreSQL, MySQL, and SQLite;
  dialect-specific storage is handled internally. Verified by a shared
  contract suite (CRUD, FK/unique/check violations, transactions, atomic
  bulk, record-level authz) that runs unchanged on all three. Accepted
  differences: `datetime` reads are naive on SQLite/MySQL, and text/enum
  fields need `length` when indexed on MySQL.
- **`keelpolicy` authorization.** Deny-overrides YAML policy engine,
  application-owned, no DB dependency — reusable outside KeelModel.
- **Same-transaction audit.** Optional extension records every mutation with
  subject and redacted field diffs in the same commit.
- **Alembic draft generation.** Migrations are generated for review — never
  applied silently.

## Layout

| Path | Purpose |
| ---- | ------- |
| `src/keelmodel/` | schema, generation, registry, runtime, extensions |
| `src/keelpolicy/` | standalone YAML policy parser + evaluator |
| `examples/sales/` | small module: Customer → Invoice → InvoiceLine |
| `examples/erp/` | heavier module: departments, self-refs, M2M junctions, milestones — with a stress harness |

```bash
uv run pytest                        # unit tests
KEELMODEL_TEST_DB=postgresql://…     # + Postgres integration
KEELMODEL_TEST_MYSQL=mysql+pymysql://…  # + MySQL integration
KEELMODEL_DB=… uv run python examples/erp/stress.py
```

## Status

Early development (v0.1). Sync API only; authorization enforcement is
opt-in pending a security review. No HTTP layer, no async yet.
