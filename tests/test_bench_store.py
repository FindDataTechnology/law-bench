"""Kernel knowledge-unit store (add-knowledge-bench-platform, task 2.1).

Covers the domain-neutral unit store and the additive eval_runs columns:
- a brand-new kind (no kernel branching) round-trips through upsert/get/list;
- upsert identity is (kind, namespace, external_key);
- tier CHECK rejects unknown tiers;
- eval_runs gains channel/unit_kind with legacy-safe defaults.
"""

from __future__ import annotations

import pytest

from src.bench.store import (
    get_knowledge_unit,
    list_knowledge_units,
    upsert_knowledge_unit,
)
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Inject the fixture's own connection so DDL lands on the per-test DB
    # instead of the process-wide cached shared connection (which stays bound
    # to whichever test DB connected first).
    ensure_schema(db_path=empty_db)
    yield empty_db


def test_new_kind_round_trips_without_kernel_branching(db_conn):
    stored = upsert_knowledge_unit(
        db_conn,
        kind="indicator",
        external_key="ind-001",
        body="某指标 2026-10 数值为 42",
        namespace="testns",
        tags={"domain": "t"},
        attrs={"period": "2026-10", "value": 42},
        tier="silver",
        provenance={"source": "test"},
    )
    assert stored["kind"] == "indicator"
    assert stored["tier"] == "silver"
    assert stored["attrs"]["value"] == 42

    fetched = get_knowledge_unit(
        db_conn, kind="indicator", external_key="ind-001", namespace="testns"
    )
    assert fetched["id"] == stored["id"]
    assert fetched["body"] == "某指标 2026-10 数值为 42"


def test_upsert_identity_is_kind_namespace_external_key(db_conn):
    a = upsert_knowledge_unit(
        db_conn, kind="qa-pair", external_key="k1", body="v1", namespace="testns"
    )
    b = upsert_knowledge_unit(
        db_conn, kind="qa-pair", external_key="k1", body="v2", namespace="testns"
    )
    assert a["id"] == b["id"]
    assert b["body"] == "v2"
    assert len(list_knowledge_units(db_conn, kind="qa-pair", namespace="testns")) == 1


def test_unknown_tier_rejected(db_conn):
    from psycopg.errors import CheckViolation

    with pytest.raises(CheckViolation):
        upsert_knowledge_unit(
            db_conn, kind="fact", external_key="bad-tier", body="x", tier="diamond"
        )


def test_eval_runs_channel_columns_present(db_conn):
    cols = {
        r["column_name"]
        for r in db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'eval_runs'"
        ).fetchall()
    }
    assert {"channel", "unit_kind"} <= cols


def test_legacy_eval_insert_reads_as_clause_text(db_conn):
    from src.eval import store as eval_store

    run_id = eval_store.store_result(
        {
            "rubric": "r",
            "score": 1.0,
            "max_score": 1.0,
            "all_pass": 1,
            "n_criteria": 1,
            "n_passed": 1,
            "criteria": [],
        },
        db_path=db_conn,
    )
    row = db_conn.execute(
        "SELECT channel, unit_kind FROM eval_runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert (row["channel"], row["unit_kind"]) == ("text", "clause")
