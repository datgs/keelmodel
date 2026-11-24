"""Run the Sales walkthrough as an end-to-end acceptance test.

SQLite always runs (temporary file). Postgres runs only when
KEELMODEL_DEMO_PG points to a dedicated test database — additive only,
never skipped-as-pass.
"""

import os
import subprocess
import sys

import pytest

DEMO = "examples/sales/demo.py"

EXPECTED = [
    "filtered query finds the invoice",
    "viewer denied draft invoice",
    "viewer query only sees submitted/paid invoices",
    "viewer reads a paid invoice",
    "tax_id omitted from viewer output",
    "viewer cannot filter on tax_id",
    "viewer cannot create invoices",
    "invalid row aborts the transaction",
    "rolled-back row is not persisted",
    "generated class queries",
    "migration draft executed upgrade",
    "audit entry recorded",
    "email redacted in audit",
    "all bulk rows queryable",
]


def _run_demo(env_extra: dict[str, str], *argv: str) -> str:
    env = {**os.environ, **env_extra}
    result = subprocess.run(
        [sys.executable, DEMO, *argv],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, f"demo failed:\n{result.stdout}\n{result.stderr}"
    return result.stdout


def _assert_walkthrough(output: str) -> None:
    for label in EXPECTED:
        assert f"[PASS] {label}" in output, (
            f"missing expected outcome {label!r}:\n{output}"
        )
    assert "[FAIL]" not in output, output


def test_demo_walkthrough_sqlite():
    _assert_walkthrough(_run_demo({}))


@pytest.mark.skipif(
    not os.environ.get("KEELMODEL_DEMO_PG"),
    reason="KEELMODEL_DEMO_PG not set — needs a dedicated test database",
)
def test_demo_walkthrough_postgres():
    env = {"KEELMODEL_DEMO_PG": os.environ["KEELMODEL_DEMO_PG"]}
    # first run resets the (dedicated) schema in case of drift
    _assert_walkthrough(_run_demo({**env, "KEELMODEL_RESET": "1"}, "--postgres"))
    # second run proves additive re-runnability without reset
    _assert_walkthrough(_run_demo(env, "--postgres"))
