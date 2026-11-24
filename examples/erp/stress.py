"""ERP sample app: complex relations + heavier stress test.

Usage:
    KEELMODEL_DB="postgresql://postgres:postgres@localhost:5544/postgres" \
        uv run python examples/erp/stress.py
    KEELMODEL_DB="mysql+pymysql://root:root@localhost:3307/keeltest" \
        uv run python examples/erp/stress.py
    KEELMODEL_DB="sqlite:///erp_stress.db" uv run python examples/erp/stress.py

    # sustained mixed workload (create/update/delete/read) for N seconds:
    KEELMODEL_RESET=1 KEELMODEL_DB="postgresql://…" \
        uv run python examples/erp/stress.py --duration 3600
"""

from __future__ import annotations

import os
import random
import sys
import time
import uuid
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


def sustained(km: KeelModel, admin: OperationContext, seconds: int) -> None:
    """Continuous mixed workload until `seconds` elapse.

    Mix: bulk creates, updates, deletes, filtered queries, point reads,
    and expected authz denials. Unexpected errors are tallied, not
    swallowed silently — they surface in the per-minute report.
    """
    staff = OperationContext(subject={"roles": ["staff"]}, attributes={})

    dept = km.bulk(
        "erp.Department", [{"name": f"Stress Dept {uuid.uuid4().hex[:8]}"}], admin
    )[0]
    dept_id = str(dept["id"])

    stats = {"create": 0, "update": 0, "delete": 0, "read": 0,
             "denied": 0, "errors": 0}
    project_pool: list[str] = []
    employee_pool: list[str] = []
    role_pool: list[str] = []
    milestone_pool: list[str] = []

    def seed() -> None:
        roles = km.bulk(
            "erp.Role", [{"code": f"R{uuid.uuid4().hex[:8]}"}], admin
        )
        role_pool.append(str(roles[0]["id"]))
        emps = km.bulk(
            "erp.Employee",
            [
                {
                    "full_name": f"SE{i}",
                    "email": f"https://se{i}-{uuid.uuid4().hex[:6]}.example",
                    "salary": random.randint(30_000, 200_000),
                    "department_id": dept_id,
                }
                for i in range(20)
            ],
            admin,
        )
        employee_pool.extend(str(e["id"]) for e in emps)
        projs = km.bulk(
            "erp.Project",
            [
                {
                    "code": f"SP-{uuid.uuid4().hex[:8]}-{i}",
                    "title": f"Stress Project {i}",
                    "budget": random.randint(10_000, 5_000_000),
                    "owner_id": random.choice(employee_pool),
                }
                for i in range(5)
            ],
            admin,
        )
        project_pool.extend(str(p["id"]) for p in projs)
        stats["create"] += len(emps) + len(projs) + len(roles)

    def op_create() -> None:
        batch = km.bulk(
            "erp.Milestone",
            [
                {
                    "name": f"SM-{uuid.uuid4().hex[:10]}",
                    "done": random.random() < 0.4,
                    "project_id": random.choice(project_pool),
                    "approver_id": random.choice(employee_pool),
                }
                for _ in range(50)
            ],
            admin,
        )
        milestone_pool.extend(str(m["id"]) for m in batch)
        stats["create"] += len(batch)

    def op_update() -> None:
        if not milestone_pool:
            return
        for mid in random.sample(milestone_pool, min(20, len(milestone_pool))):
            km.update("erp.Milestone", mid, {"done": random.random() < 0.5}, admin)
            stats["update"] += 1

    def op_delete() -> None:
        if not milestone_pool:
            return
        # pick tail of pool so deletes don't churn fresh inserts
        k = min(20, len(milestone_pool))
        for mid in milestone_pool[:k]:
            km.delete("erp.Milestone", mid, admin)
            stats["delete"] += 1
        del milestone_pool[:k]

    def op_query() -> None:
        for _ in range(5):
            km.query(
                "erp.Milestone",
                admin,
                filters={
                    "all": [
                        {"field": "done", "op": "eq", "value": random.random() < 0.5},
                        {"field": "project_id", "op": "eq",
                         "value": random.choice(project_pool)},
                    ]
                },
                limit=25,
            )
            stats["read"] += 1

    def op_get() -> None:
        for _ in range(10):
            km.get("erp.Employee", random.choice(employee_pool), admin)
            stats["read"] += 1

    def op_denied() -> None:
        for _ in range(5):
            try:
                km.create("erp.Role", {"code": f"X{uuid.uuid4().hex[:8]}"}, staff)
            except Exception:
                stats["denied"] += 1

    ops = [op_create, op_update, op_delete, op_query, op_get, op_denied]
    weights = [30, 20, 15, 15, 10, 10]

    started = time.monotonic()
    deadline = started + seconds
    minute = 1
    last_report = started
    while time.monotonic() < deadline:
        if not project_pool or not employee_pool or not role_pool:
            seed()
        try:
            random.choices(ops, weights)[0]()
        except Exception as exc:
            stats["errors"] += 1
            print(f"  [ERR] {type(exc).__name__}: {exc}", flush=True)
        now = time.monotonic()
        if now - last_report >= 60:
            elapsed = now - started
            total = sum(v for k, v in stats.items() if k != "errors")
            print(
                f"min {minute:>3} | creates={stats['create']:>7,} "
                f"updates={stats['update']:>7,} deletes={stats['delete']:>7,} "
                f"reads={stats['read']:>7,} denials={stats['denied']:>4,} "
                f"errors={stats['errors']:>3} | {total/elapsed:6,.0f} ops/s",
                flush=True,
            )
            minute += 1
            last_report = now
    total = sum(v for k, v in stats.items() if k != "errors")
    print(
        f"done in {time.monotonic()-started:.0f}s | total={total:,} ops "
        f"({total/(time.monotonic()-started):,.0f} ops/s), "
        f"errors={stats['errors']}, denials={stats['denied']}",
        flush=True,
    )


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

    if "--duration" in sys.argv:
        idx = sys.argv.index("--duration")
        seconds = int(sys.argv[idx + 1])
        sustained(km, admin, seconds)
        return 0

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
