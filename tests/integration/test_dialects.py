"""Cross-dialect proof: the same YAML schema + SDK contract works on
PostgreSQL, SQLite, and MySQL without changing application code.
"""

import os
import uuid

import pytest

from keelmodel.registry import ModuleDefinition, ModuleRegistry
from keelmodel.runtime.context import OperationContext
from keelmodel.runtime.session import KeelModel
from keelmodel.schema import parse_model

CTX = OperationContext(subject={"roles": ["admin"]}, attributes={})


def _build(db_url: str, suffix: str) -> KeelModel:
    team = parse_model(
        {
            "version": 1,
            "module": "hr",
            "model": "Team",
            "table": f"hr_team_{suffix}",
            "fields": {
                "id": {"type": "uuid", "primary_key": True, "default": "uuid4"},
                "name": {"type": "text", "required": True},
            },
        }
    )
    member = parse_model(
        {
            "version": 1,
            "module": "hr",
            "model": "Member",
            "table": f"hr_member_{suffix}",
            "fields": {
                "id": {"type": "uuid", "primary_key": True, "default": "uuid4"},
                "name": {"type": "text", "required": True},
                "level": {"type": "integer", "default": 0},
            },
            "relations": {
                "team": {
                    "type": "many_to_one",
                    "target": "hr.Team",
                    "required": True,
                }
            },
        }
    )
    registry = ModuleRegistry()
    registry.register(
        ModuleDefinition(
            name="hr",
            version="1.0.0",
            requires=(),
            exports=("Team", "Member"),
            models_path="models",
        ),
        (team, member),
    )
    km = KeelModel(db_url, registry)
    for t in (km._all_mapped["hr.Team"].__table__, km._all_mapped["hr.Member"].__table__):
        t.create(km.engine, checkfirst=True)
    return km


def _roundtrip(km: KeelModel) -> None:
    team = km.create("hr.Team", {"name": "Platform"}, CTX)
    member = km.create(
        "hr.Member", {"name": "Ana", "level": 3, "team_id": str(team["id"])}, CTX
    )
    assert member["team_id"] == team["id"]

    fetched = km.get("hr.Member", member["id"], CTX)
    assert fetched["name"] == "Ana"

    updated = km.update("hr.Member", member["id"], {"level": 4}, CTX)
    assert updated["level"] == 4

    page = km.query(
        "hr.Member",
        CTX,
        filters={"field": "level", "op": "gte", "value": 4},
    )
    assert page.total == 1

    km.delete("hr.Member", member["id"], CTX)
    km.delete("hr.Team", team["id"], CTX)


def test_sqlite_roundtrip(tmp_path):
    suffix = uuid.uuid4().hex[:8]
    km = _build(f"sqlite:///{tmp_path}/keel.db", suffix)
    assert km.engine.dialect.name == "sqlite"
    _roundtrip(km)


@pytest.mark.skipif(
    not os.environ.get("KEELMODEL_TEST_DB"), reason="needs KEELMODEL_TEST_DB"
)
def test_postgres_roundtrip():
    suffix = uuid.uuid4().hex[:8]
    km = _build(os.environ["KEELMODEL_TEST_DB"], suffix)
    assert km.engine.dialect.name == "postgresql"
    _roundtrip(km)


@pytest.mark.skipif(
    not os.environ.get("KEELMODEL_TEST_MYSQL"), reason="needs KEELMODEL_TEST_MYSQL"
)
def test_mysql_roundtrip():
    suffix = uuid.uuid4().hex[:8]
    km = _build(os.environ["KEELMODEL_TEST_MYSQL"], suffix)
    assert km.engine.dialect.name == "mysql"
    _roundtrip(km)
