"""写入边界的键归名：五个写入方共用一把尺子。

实测背景（2026-11-09）：归名只发生在取目录与抽取两个调用方，脚本忘了 import
pack 就写出 401 条 `中华人民共和国民法典#第N条`，与 `民法典#第N条` 并存，最后
全部退掉重来。这组测试钉住的是"写入口自己会归名"，不依赖调用方记得。
"""

from __future__ import annotations

import json
import pytest

import packs.legal  # noqa: F401 — registers the legal rules
from src.bench import authoring, keys, proposals, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema

SCHEMA = {
    "entity_types": ["clause", "law", "concept"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["defines"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}

#: 一个没有任何 pack 注册规则的域（"只需要机制、还没有词表"的真实状态）。
UNRULED = "gastro"


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    for key in ("legal", UNRULED):
        workspaces.instantiate_domain(
            conn=empty_db, key=key, name=key, template_name="tpl",
            template_version=None, created_by="t",
        )
    # add-fleet-execution-loop: fleet: sources now need a live registration.
    from _fleet_fixtures import provision_default_fleet_world
    provision_default_fleet_world(empty_db)
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def test_an_unfolded_key_is_folded_at_the_write_boundary(conn):
    authoring.authoring_create_unit(
        conn, domain_key="legal", kind="law",
        external_key="中华人民共和国合同法", body="# 合同法", operator="t",
    )
    unit = authoring.authoring_get_unit(
        conn, domain_key="legal", kind="law", external_key="合同法")
    assert unit is not None, "写入应落在归名后的键上"
    assert unit["attrs"]["aliases"] == ["中华人民共和国合同法"]
    assert unit["attrs"]["folded_by"] == ["drop-prc"]
    assert authoring.authoring_get_unit(
        conn, domain_key="legal", kind="law",
        external_key="中华人民共和国合同法") is None, "不得同时留下原写法"


def test_two_spellings_land_in_one_row(conn):
    for raw in ("中华人民共和国合同法", "合同法"):
        authoring.authoring_create_unit(
            conn, domain_key="legal", kind="law", external_key=raw, body="b", operator="t")
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_units WHERE namespace='legal' AND kind='law'"
    ).fetchone()
    assert rows["n"] == 1


def test_batch_dedupes_on_the_folded_key(conn):
    with pytest.raises(ValueError, match="duplicate key in one batch"):
        authoring.authoring_create_units(
            conn, domain_key="legal", operator="t",
            units=[
                {"kind": "clause", "external_key": "中华人民共和国合同法#第1条", "body": "甲"},
                {"kind": "clause", "external_key": "合同法#第1条", "body": "乙"},
            ],
        )
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_units WHERE namespace='legal'"
    ).fetchone()["n"] == 0, "整批应回滚"


def test_a_domain_without_rules_is_left_alone(conn):
    authoring.authoring_create_unit(
        conn, domain_key=UNRULED, kind="law",
        external_key="中华人民共和国某办法", body="b", operator="t")
    unit = authoring.authoring_get_unit(
        conn, domain_key=UNRULED, kind="law", external_key="中华人民共和国某办法")
    assert unit is not None
    assert "aliases" not in (unit["attrs"] or {})


def test_proposal_keys_are_folded_and_the_original_is_kept_readable(conn):
    proposal = proposals.submit(
        conn, domain_key="legal", source="fleet:abc/post-1", kind="law",
        external_key="中华人民共和国合同法", body="合同法",
        evidence={"stable_id": "http://example/1"}, submitted_by="fleet:abc/post-1",
    )
    assert proposal["external_key"] == "合同法"
    assert "中华人民共和国合同法" in (proposal["impact"] or "")

    proposals.confirm(conn, domain_key="legal", proposal_id=proposal["id"],
                      actor="lead@example.com")
    assert authoring.authoring_get_unit(
        conn, domain_key="legal", kind="law", external_key="合同法") is not None


def test_folding_is_stable(conn):
    """Same input, same key — twice, and across the two write paths."""
    first = keys.fold("中华人民共和国合同法", keys.rules_for("legal"))[0]
    second = keys.fold("中华人民共和国合同法", keys.rules_for("legal"))[0]
    assert first == second == "合同法"


# ── 历史存量对账（authoring_fold_existing_keys） ────────────────────────────


def _raw_unit(conn, kind, key, attrs=None):
    """直接写一行，绕过写入口——模拟"归名之前写进去的历史行"。"""
    conn.execute(
        "INSERT INTO knowledge_units (kind, namespace, external_key, body, attrs, "
        "created_at, updated_at) VALUES (%s,'legal',%s,'b',%s::jsonb,'now','now')",
        (kind, key, json.dumps(attrs or {})),
    )
    conn.commit()


def test_dry_run_reports_without_changing_anything(conn):
    _raw_unit(conn, "law", "中华人民共和国合同法")
    out = authoring.authoring_fold_existing_keys(conn, domain_key="legal", dry_run=True)
    assert out["renamed"] == 1 and out["dry_run"] is True
    assert out["plan"][0]["new"] == "合同法"
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_units WHERE external_key='中华人民共和国合同法'"
    ).fetchone()["n"] == 1, "dry-run 不得改库"


def test_a_historical_key_is_renamed_in_place_and_records_the_alias(conn):
    _raw_unit(conn, "law", "中华人民共和国合同法", attrs={"corpus": {"doc_id": "1"}})
    before_id = conn.execute(
        "SELECT id FROM knowledge_units WHERE external_key='中华人民共和国合同法'"
    ).fetchone()["id"]
    out = authoring.authoring_fold_existing_keys(conn, domain_key="legal", dry_run=False)
    assert out["renamed"] == 1
    row = conn.execute(
        "SELECT id, external_key, attrs FROM knowledge_units WHERE kind='law'").fetchone()
    assert row["external_key"] == "合同法"
    assert row["id"] == before_id, "行 id 不能变：它是审计锚"
    assert row["attrs"]["aliases"] == ["中华人民共和国合同法"]
    assert row["attrs"]["corpus"] == {"doc_id": "1"}, "其它 attrs 必须原样保留"


def test_a_key_with_a_twin_is_left_alone(conn):
    _raw_unit(conn, "law", "中华人民共和国合同法")
    _raw_unit(conn, "law", "合同法")
    out = authoring.authoring_fold_existing_keys(conn, domain_key="legal", dry_run=False)
    assert out["renamed"] == 0 and out["skipped_twin"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"] == 2


def test_a_relation_pointing_at_the_old_key_is_rewritten(conn):
    _raw_unit(conn, "law", "中华人民共和国合同法")
    authoring.authoring_create_unit(conn, domain_key="legal", kind="clause",
                                    external_key="合同法#第1条", body="b", operator="t")
    authoring.authoring_create_relationship(
        conn, domain_key="legal", kind="defines",
        from_key="中华人民共和国合同法", to_key="合同法#第1条",
        body="x", operator="t")
    authoring.authoring_fold_existing_keys(conn, domain_key="legal", dry_run=False)
    rel = conn.execute(
        "SELECT external_key, attrs FROM knowledge_units WHERE kind='defines'").fetchone()
    assert rel["external_key"] == "合同法->defines:合同法#第1条"
    assert rel["attrs"]["from_key"] == "合同法"


def test_the_reconciliation_is_idempotent(conn):
    _raw_unit(conn, "law", "中华人民共和国合同法")
    authoring.authoring_fold_existing_keys(conn, domain_key="legal", dry_run=False)
    again = authoring.authoring_fold_existing_keys(conn, domain_key="legal", dry_run=False)
    assert again["renamed"] == 0


def test_a_domain_without_rules_is_refused_with_a_reason(conn):
    out = authoring.authoring_fold_existing_keys(conn, domain_key=UNRULED, dry_run=True)
    assert out["renamed"] == 0
    assert "未注册归名规则" in out["reason"]
