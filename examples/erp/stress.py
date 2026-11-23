"""ERP sample app: complex relations + heavier stress test.

Usage:
    KEELMODEL_DB="postgresql://postgres:postgres@localhost:5544/postgres" \
        uv run python examples/erp/stress.py
    KEELMODEL_DB="mysql+pymysql://root:root@localhost:3307/keeltest" \
        uv run python examples/erp/stress.py
    KEELMODEL_DB="sqlite:///erp_stress.db" uv run python examples/erp/stress.py
"""

from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

from keelmodel.authz import AuthorizationProvider
from keelmodel.extensions.audit import AuditExtension
from keelmodel.registry import ModuleRegistry, load_module
from keelmodel.runtime.base import Base
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.session import KeelModel
from keelmodel.schema import load_model

ROOT = Path(__file__).parent
DB_URL = os.environ.get("KEELMODEL_DB")

N_DEPARTMENTS = 20
N_EMPLOYEES = 2_000
N_ROLES = 30
N_ASSIGNMENTS = 5_000
N_PROJECTS = 800
N_MILESTONES = 8_000
N_QUERIES = 1_000


def build() -> KeelModel:
    module = load_module(ROOT / "keelmodule.yaml")
    models = [load_model(p) for p in sorted((ROOT / "models").glob("*.yaml"))]
    registry = ModuleRegistry()
    registry.register(module, models)
    authz = AuthorizationProvider(ROOT / "policies" / "authorization.yaml")
    audit = AuditExtension(redact_fields={"salary", "email"})
    km = KeelModel(DB_URL, registry, authz=authz, audit=audit)
    if os.environ.get("KEELMODEL_RESET") == "1":
        Base.metadata.drop_all(km.engine, checkfirst=True)
        audit.table.drop(km.engine, checkfirst=True)
    Base.metadata.create_all(km.engine)
    audit.create_all(km.engine)
    return km


def timed(label: str, fn, count: int) -> float:
    started = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - started
    print(f"{label:34s} {count:>7,} rows  {elapsed:7.2f}s  ({count/elapsed:8,.0f}/s)")
    return result


def main() -> int:
    if not DB_URL:
        print("set KEELMODEL_DB", file=sys.stderr)
        return 2
    random.seed(42)
    print(f"dialect: {DB_URL.split('://')[0]}")
    km = build()
    admin = OperationContext(subject={"roles": ["admin"]}, attributes={})

    departments = timed(
        "bulk departments",
        lambda: km.bulk(
            "erp.Department", [{"name": f"Dept {i}"} for i in range(N_DEPARTMENTS)], admin
        ),
        N_DEPARTMENTS,
    )
    dept_ids = [str(d["id"]) for d in departments]

    employees = timed(
        "bulk employees",
        lambda: km.bulk(
            "erp.Employee",
            [
                {
                    "full_name": f"Employee {i}",
                    "email": f"https://e{i}.example",
                    "salary": random.randint(30_000, 200_000),
                    "department_id": random.choice(dept_ids),
                }
                for i in range(N_EMPLOYEES)
            ],
            admin,
        ),
        N_EMPLOYEES,
    )
    emp_ids = [str(e["id"]) for e in employees]

    roles = timed(
        "bulk roles",
        lambda: km.bulk("erp.Role", [{"code": f"ROLE_{i}"} for i in range(N_ROLES)], admin),
        N_ROLES,
    )
    role_ids = [str(r["id"]) for r in roles]

    pairs = set()
    while len(pairs) < N_ASSIGNMENTS:
        pairs.add((random.choice(emp_ids), random.choice(role_ids)))
    timed(
        "bulk role assignments (M2M junction)",
        lambda: km.bulk(
            "erp.RoleAssignment",
            [
                {"employee_id": e, "role_id": r, "granted_by": "seed"}
                for e, r in pairs
            ],
            admin,
        ),
        N_ASSIGNMENTS,
    )

    projects = timed(
        "bulk projects",
        lambda: km.bulk(
            "erp.Project",
            [
                {
                    "code": f"PRJ-{i}",
                    "title": f"Project {i}",
                    "budget": random.randint(10_000, 5_000_000),
                    "owner_id": random.choice(emp_ids),
                }
                for i in range(N_PROJECTS)
            ],
            admin,
        ),
        N_PROJECTS,
    )
    project_ids = [str(p["id"]) for p in projects]

    timed(
        "bulk milestones",
        lambda: km.bulk(
            "erp.Milestone",
            [
                {
                    "name": f"M{i}",
                    "done": random.random() < 0.4,
                    "project_id": random.choice(project_ids),
                    "approver_id": random.choice(emp_ids),
                }
                for i in range(N_MILESTONES)
            ],
            admin,
        ),
        N_MILESTONES,
    )

    timed(
        "filtered queries",
        lambda: [
            km.query(
                "erp.Milestone",
                admin,
                filters={
                    "all": [
                        {"field": "done", "op": "eq", "value": False},
                        {"field": "project_id", "op": "eq", "value": random.choice(project_ids)},
                    ]
                },
            )
            for _ in range(N_QUERIES)
        ],
        N_QUERIES,
    )

    timed(
        "mixed reads (get + query)",
        lambda: [
            km.get("erp.Employee", random.choice(emp_ids), admin)
            if i % 2
            else km.query(
                "erp.Project",
                admin,
                filters={"field": "budget", "op": "gte", "value": random.randint(0, 5_000_000)},
                limit=20,
            )
            for i in range(N_QUERIES)
        ],
        N_QUERIES,
    )

    staff = OperationContext(subject={"roles": ["staff"]}, attributes={})
    denied = 0
    for _ in range(100):
        try:
            km.create("erp.Role", {"code": f"X{random.random()}"}, staff)
        except Exception:
            denied += 1
    print(f"{'authz denials (staff create)':34s} {denied:>7,} / 100")

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
