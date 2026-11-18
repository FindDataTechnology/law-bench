"""LIBRARY_SCHEMA must survive the *deployed* legacy table shapes.

Regression guard for the 2026-11-08 production crash-loop: the deployed
``rubrics`` table was created by a legacy script and has **no primary key**, so
any ``REFERENCES rubrics(id)`` in the additive DDL fails at boot with
``InvalidForeignKey`` and takes the whole app down.

This test builds the legacy shapes first (no PKs where production has none),
then applies the schema — the same order production goes through on a restart.
"""

from __future__ import annotations

import pytest

from src.bench.libraries import LIBRARY_SCHEMA
from src.bench.store import BENCH_SCHEMA
from src.bench.workspace_store import WORKSPACE_SCHEMA
from src.eval import store as eval_store
from src.eval.store import ensure_schema


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    yield empty_db


def test_schema_applies_over_pk_less_legacy_rubrics(conn):
    """The real production shape: rubrics/criteria exist but carry no PK."""
    conn.execute(
        """
        CREATE TABLE rubrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY,
            name TEXT NOT NULL,
            context TEXT,
            source TEXT,
            source_path TEXT,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE criteria (
            id BIGINT GENERATED ALWAYS AS IDENTITY,
            rubric_id BIGINT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            guidance TEXT,
            ordinal INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "INSERT INTO rubrics (name, context, source, description) "
        "VALUES ('legacy-one', 'check', 'seed', 'd')"
    )
    conn.commit()

    # Production applies these in exactly this order at boot.
    conn.execute(BENCH_SCHEMA)
    conn.execute(WORKSPACE_SCHEMA)
    conn.execute(LIBRARY_SCHEMA)  # must not raise InvalidForeignKey
    conn.execute(
        "INSERT INTO ontology_templates (name, version, schema, created_by) "
        "VALUES ('legacy-tpl', 1, '{\"entity_types\":[\"x\"],\"relationship_kinds\":[\"r\"],"
        "\"tier_vocabulary\":[\"raw\",\"bronze\",\"silver\",\"gold\"],"
        "\"sensitivity_vocabulary\":[\"public\",\"internal\",\"confidential\"],"
        "\"concept_structures\":{},\"corpus_declaration\":{}}', 't')"
    )
    conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "SELECT 'legal','法律域',id,1,'t','legal' FROM ontology_templates ORDER BY id LIMIT 1"
    )
    conn.commit()
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=conn)  # the full boot path, idempotent

    # The legacy rubric acquired an owner and the new columns exist.
    row = conn.execute(
        "SELECT domain_id, derived_from, fork_diff FROM rubrics WHERE name='legacy-one'"
    ).fetchone()
    assert row["derived_from"] is None and row["fork_diff"] is None
    assert row["domain_id"] is not None


def test_fork_still_records_parent_without_a_foreign_key(conn):
    """The soft reference must still behave: a fork points at its parent id."""
    from src.bench import domain_rubrics, templates
    from src.bench.promotion import SENSITIVITY_LEVELS
    from src.bench.tiers import TIERS

    conn.execute(
        """
        CREATE TABLE rubrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY,
            name TEXT NOT NULL, context TEXT, source TEXT, source_path TEXT,
            description TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())
        """
    )
    conn.execute(
        """
        CREATE TABLE criteria (
            id BIGINT GENERATED ALWAYS AS IDENTITY, rubric_id BIGINT NOT NULL,
            name TEXT NOT NULL, description TEXT, guidance TEXT,
            ordinal INTEGER NOT NULL DEFAULT 0)
        """
    )
    conn.commit()
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=conn)

    templates.create_template(
        conn,
        name="t",
        schema={
            "entity_types": ["x"], "concept_structures": {"x": ["id"]},
            "relationship_kinds": ["r"], "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": []},
        },
        created_by="t",
    )
    tid = conn.execute("SELECT id FROM ontology_templates LIMIT 1").fetchone()["id"]
    dom = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "VALUES ('d1','D1',%s,1,'t','d1') RETURNING id", (tid,)
    ).fetchone()["id"]
    conn.commit()

    parent = domain_rubrics.create_for_domain(
        conn, domain_id=dom, name="p", context="c", criteria=[{"name": "a"}]
    )
    # A fork lives in the adopting domain under its own name (same-domain forks
    # would collide with the per-domain unique name, by design).
    forked = domain_rubrics.fork(
        conn, source_rubric_id=parent["id"], domain_id=dom, name="p-fork",
        fork_diff={"criteria": {"a": "raised"}},
    )
    assert forked["derived_from"] == parent["id"]
    assert forked["fork_diff"]["criteria"]["a"] == "raised"
