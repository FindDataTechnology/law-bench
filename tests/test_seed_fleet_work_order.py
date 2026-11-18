"""派单脚本 `scripts/seed_fleet_work_order.py` 的守门行为（add-fleet-execution-loop §6.4）。

这个脚本存在的唯一理由是：**生产上派单只有控制台那一条路**（Logto 会话），而验收要
一张真的派给舰队的单。所以它必须只做那件事，且三面都堵住：

- **没登记的舰队不给派单**（和库里 `authoring_create_task` 同一个校验，脚本不绕过它）；
- **dry run 一行都不写**（一份说「会建」的 dry run 比什么都没有更坏）；
- **写进去的必须是 `assignee_kind=fleet` + `assignee_ref`**，而不是一个人名——
  `fleet` 档的授权读的是这两个字段，读 `assignee` 那个给人看的标签会读成没主。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.bench import templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_fleet_work_order.py"
FLEET_REF = "fleet_1794335712751_wfa3ww"


def _load_script():
    spec = importlib.util.spec_from_file_location("seed_fleet_work_order_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    schema = {
        "entity_types": ["clause", "law", "concept"],
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


def _tasks(conn):
    return conn.execute(
        "SELECT id, status, assignee, assignee_kind, assignee_ref FROM authoring_tasks ORDER BY id"
    ).fetchall()


def _register(conn, *, kind="fleet", fleet_ref=FLEET_REF):
    from src.bench import distribution
    import hashlib

    return distribution.register_consumer(
        conn, name="ontology-fleet-win", domains=["legal"],
        token_hash=hashlib.sha256(b"tok").hexdigest(), created_by="t",
        kind=kind, fleet_ref=fleet_ref if kind == "fleet" else None,
    )


def test_it_refuses_a_fleet_that_is_not_registered(conn, capsys):
    """没登记就派单＝派给不存在的执行者；库层会拒，脚本必须先拒并说清为什么。"""
    script = _load_script()
    rc = script.main([
        "--fleet-ref", FLEET_REF, "--domain", "legal", "--title", "t", "--apply",
    ])
    assert rc == 1
    assert "不是本域可用的舰队登记" in capsys.readouterr().err
    assert _tasks(conn) == []


def test_dry_run_writes_nothing(conn, capsys):
    _register(conn)
    script = _load_script()
    assert script.main(["--fleet-ref", FLEET_REF, "--domain", "legal", "--title", "t"]) == 0
    assert "would create ONE pending task" in capsys.readouterr().out
    assert _tasks(conn) == []


def test_apply_creates_a_task_addressed_to_the_fleet(conn, capsys):
    _register(conn)
    script = _load_script()
    assert script.main([
        "--fleet-ref", FLEET_REF, "--domain", "legal", "--title", "验收单", "--apply",
    ]) == 0
    rows = _tasks(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "pending"
    # 授权读的是这两列；`assignee` 只是给人看的标签。
    assert row["assignee_kind"] == "fleet"
    assert row["assignee_ref"] == FLEET_REF
    assert "created task id=" in capsys.readouterr().out
