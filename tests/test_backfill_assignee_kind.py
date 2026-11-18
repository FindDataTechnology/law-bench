"""存量派单行的类型化回填（add-fleet-execution-loop §6.1）。

新列带 ``DEFAULT 'human'``，于是**所有旧行都自称是人派的**。对 ``agent:`` /
``fleet:`` 形状的行来说这句是假的，而且错的方向很危险：控制台会把工单递给一个
根本处理不了它的人，真正负责这个缺口的内核岗位永远看不到。

所以脚本只认平台自己铸的两种形状，其余（含 ``alice@example.com``）保持 human——
人名的确是人。展示列 ``assignee`` 一个字都不改：它的读者是人，本脚本管的是授权。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.bench import authoring, distribution, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backfill_assignee_kind.py"


def _load():
    spec = importlib.util.spec_from_file_location("backfill_assignee_kind", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    schema = {
        "entity_types": ["company"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    templates.create_template(conn=empty_db, name="tpl", schema=schema, created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    yield empty_db


def _legacy_task(conn, assignee: str, key: str = "k") -> int:
    """Write a row the way it existed before the column: kind defaults to human."""
    domain = workspaces.get_domain(conn, domain_key="legal")
    row = conn.execute(
        "INSERT INTO authoring_tasks (domain_id, assignee, title, target_kind, "
        "target_key, created_by) VALUES (%s, %s, 't', 'estate-gap', %s, 'lead') "
        "RETURNING id",
        (domain["id"], assignee, key),
    ).fetchone()
    conn.commit()
    return row["id"]


# --------------------------------------------------------------- classify


def test_classify_reads_the_two_minted_shapes():
    mod = _load()
    assert mod.classify("agent:builder@legal") == ("kernel-role", "builder")
    assert mod.classify("fleet:fleet_1794335712751_wfa3ww/post_1") == (
        "fleet", "fleet_1794335712751_wfa3ww",
    )


def test_classify_leaves_humans_and_oddities_alone():
    mod = _load()
    for value in ("", "   ", "alice@example.com", "alice", "agent:", "agent:builder",
                  "agent:@legal", "fleet:", "fleet:/post_1"):
        assert mod.classify(value) is None, value


# ------------------------------------------------------------------ run


def test_dry_run_writes_nothing(conn, capsys):
    mod = _load()
    task_id = _legacy_task(conn, "agent:builder@legal")
    assert mod.run(conn, apply=False) == 0
    assert "dry run" in capsys.readouterr().out
    row = conn.execute(
        "SELECT assignee_kind, assignee_ref FROM authoring_tasks WHERE id = %s",
        (task_id,),
    ).fetchone()
    assert (row["assignee_kind"], row["assignee_ref"]) == ("human", None)


def test_apply_classifies_and_keeps_the_display_name(conn, capsys):
    mod = _load()
    role_id = _legacy_task(conn, "agent:builder@legal", key="ontology")
    fleet_id = _legacy_task(conn, "fleet:fleet_a/post_1", key="quality:evidence")
    human_id = _legacy_task(conn, "alice@example.com", key="quality:review_lag")

    assert mod.run(conn, apply=True) == 0
    out = capsys.readouterr().out
    assert "updated 2 row(s)" in out

    def row_parts(task_id):
        r = conn.execute(
            "SELECT assignee, assignee_kind, assignee_ref FROM authoring_tasks WHERE id = %s",
            (task_id,),
        ).fetchone()
        return (r["assignee"], r["assignee_kind"], r["assignee_ref"])

    assert row_parts(role_id) == ("agent:builder@legal", "kernel-role", "builder")
    assert row_parts(fleet_id) == ("fleet:fleet_a/post_1", "fleet", "fleet_a")
    # 人名的行不动：它本来就是人。
    assert row_parts(human_id) == ("alice@example.com", "human", None)


def test_already_typed_rows_are_never_overwritten(conn):
    """已经类型化的行一个字都不改——哪怕展示名看起来像另一种身份。"""
    mod = _load()
    domain = workspaces.get_domain(conn, domain_key="legal")
    distribution.register_consumer(
        conn, name="f", domains=["legal"],
        token_hash="0" * 64, created_by="t", kind="fleet", fleet_ref="fleet_a",
    )
    # 展示名说「这是 builder 的活」，但已类型化归属却是 fleet_a。
    # 按形状覆盖会把它从一条舰队登记挪给一个岗位——归属变了，没人知道。
    task = authoring.authoring_create_task(
        conn, domain_id=domain["id"], assignee="agent:builder@legal", title="t",
        detail="d", target_kind="estate-gap", target_key="ontology",
        created_by="lead", assignee_kind="fleet", assignee_ref="fleet_a",
    )
    mod.run(conn, apply=True)
    row = conn.execute(
        "SELECT assignee_kind, assignee_ref FROM authoring_tasks WHERE id = %s",
        (task["id"],),
    ).fetchone()
    assert (row["assignee_kind"], row["assignee_ref"]) == ("fleet", "fleet_a")


def test_a_default_human_row_is_reclassified_and_that_is_the_point(conn):
    """`human` 是列默认值，脚本**无法**区分它与「刻意的 human」。

    这条是登记在案的局限，不是遗漏：变更前的行全都带着默认值，而 ``agent:`` /
    ``fleet:`` 形状的展示名不可能是人名，所以这类行按形状改写是对的；真正刻意的
    人派单，展示名是人名，脚本不会碰。
    """
    mod = _load()
    task_id = _legacy_task(conn, "fleet:fleet_a/post_1", key="quality:evidence")
    mod.run(conn, apply=True)
    row = conn.execute(
        "SELECT assignee_kind, assignee_ref FROM authoring_tasks WHERE id = %s",
        (task_id,),
    ).fetchone()
    assert (row["assignee_kind"], row["assignee_ref"]) == ("fleet", "fleet_a")


def test_second_run_is_a_no_op(conn, capsys):
    mod = _load()
    _legacy_task(conn, "agent:builder@legal")
    mod.run(conn, apply=True)
    capsys.readouterr()
    assert mod.run(conn, apply=True) == 0
    assert "nothing to do" in capsys.readouterr().out
