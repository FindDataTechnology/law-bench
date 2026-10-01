"""Tests for the citation remediation engine (remediate-repealed-citations)."""

from __future__ import annotations

import json

import pytest

from src.law_catalog import remediate as rem
from src.law_catalog import resolve as lc_resolve
from src.law_catalog import store as lc_store
from src.law_catalog.successor_seed import seed_successor_map

_CIVIL = "中华人民共和国民法典"
_CONTRACT = "中华人民共和国合同法"


def _law(i, title, status="有效"):
    return {"id": i, "title": title, "category": "core_law", "publish": "1999-03-15",
            "expiry": "1999-10-01", "status": status, "src_db": "lawv2", "content_status": "ok"}


@pytest.fixture
def catalog(seeded_db):
    lc_store.import_catalog([
        _law(1, _CIVIL),
        _law(2, _CONTRACT, status="已废止"),
        _law(3, "中华人民共和国技术合同法", status="已废止"),  # substring trap
        _law(4, "广州市城市供水用水条例", status="已废止"),     # needs_human placeholder
        _law(5, "中华人民共和国道路运输条例", status="已修改"),
    ], db=seeded_db)
    return seeded_db


def _clause(db, cid, body, refs=None):
    if refs is None:
        from src.law_catalog.resolve import normalize_name
        import re as _re
        refs = [{"name": m, "category": "core_law", "category_zh": "核心法律"}
                for m in _re.findall(r"《([^》]+)》", body)]
    db.execute(
        "INSERT INTO clauses (id, contract_type, tags, section, body, law_refs, "
        "body_hash, created_at, updated_at) OVERRIDING SYSTEM VALUE "
        "VALUES (%s, 'sale', %s, '法律依据', %s, %s, %s, '2026-01-01', '2026-01-01')",
        (cid, json.dumps({"source": "tagged"}), body, json.dumps(refs), f"h{cid}"),
    )
    db.commit()


def _setup_resolution(db):
    lc_resolve.resolve_all_clauses(db=db)
    seed_successor_map(db=db)


def test_plan_and_apply_via_update_clause(catalog):
    _clause(catalog, 101, "双方依据《中华人民共和国合同法》签订本合同。")
    _setup_resolution(catalog)

    plan = rem.plan_batch("r1-test", db=catalog)
    assert len(plan["apply"]) == 1
    item = plan["apply"][0]
    assert item["replacements"][0]["after"] == f"《{_CIVIL}》"
    assert "民法典" in item["new_body"] and "合同法" not in item["new_body"]

    out = rem.apply_batch(plan, db=catalog)
    assert out["applied"] == 1

    row = catalog.execute("SELECT body, manual FROM clauses WHERE id = 101").fetchone()
    assert _CIVIL in row["body"] and row["manual"] is True  # canonical path side effect

    rec = catalog.execute(
        "SELECT * FROM law_catalog.citation_revisions WHERE clause_id = 101").fetchone()
    assert rec["disposition"] == "applied" and rec["dead_law_id"] == 2
    assert rec["successor_law_id"] == 1 and rec["authority_law_id"] == 1
    # evidence chain replayable: statuses checkable against the replica
    dead = lc_store.get_law(2, db=catalog); succ = lc_store.get_law(1, db=catalog)
    assert dead["status"] == "已废止" and succ["status"] == "有效"

    # snapshots exist
    from src.law_catalog.remediate import SNAPSHOT_ROOT
    before = SNAPSHOT_ROOT / "r1-test" / "before" / "101.json"
    assert before.exists() and "合同法" in before.read_text(encoding="utf-8")


def test_bare_name_boundary_never_corrupts_longer_titles(catalog):
    # law_refs derive from 《》 only, so remediation reaches a clause via the
    # bracketed form; bare mentions in the same body (（以下简称合同法）) are
    # fixed alongside, while the boundary regex keeps 技术合同法 intact
    _clause(catalog, 102, "依据《中华人民共和国合同法》（以下简称合同法）及技术合同法的有关规定订立。")
    _setup_resolution(catalog)
    plan = rem.plan_batch("r1-bare", db=catalog)
    item = [i for i in plan["apply"] if i["clause_id"] == 102][0]
    assert "《中华人民共和国民法典》（以下简称民法典）及技术合同法" in item["new_body"]


def test_narration_guard_skips_for_review(catalog):
    _clause(catalog, 103, "自合同法实施以来，实务中……依据《中华人民共和国合同法》处理。")
    _setup_resolution(catalog)
    plan = rem.plan_batch("r1-guard", db=catalog)
    by_id = {i["clause_id"]: i for i in plan["skipped_review"]}
    assert 103 in by_id
    assert 103 not in {i["clause_id"] for i in plan["apply"]}


def test_needs_human_placeholder_never_applies(catalog):
    _clause(catalog, 104, "依照《广州市城市供水用水条例》执行。")
    _setup_resolution(catalog)
    plan = rem.plan_batch("r3-test", db=catalog)
    assert 104 in {i["clause_id"] for i in plan["needs_human"]}
    assert 104 not in {i["clause_id"] for i in plan["apply"]}
    # verify target = count of needs_human citations stays honest
    v = rem.verify_batch(db=catalog)
    assert v["audit"]["repealed"] >= 1  # unmapped dead citation remains


def test_no_action_records_without_edits(catalog):
    _clause(catalog, 105, "遵守《中华人民共和国道路运输条例》的相关规定。")
    _setup_resolution(catalog)
    out = rem.record_no_action("r0-test", db=catalog)
    assert out["reviewed_no_action"] >= 1
    body = catalog.execute("SELECT body FROM clauses WHERE id = 105").fetchone()["body"]
    assert "道路运输条例" in body  # zero edits
    rec = catalog.execute(
        "SELECT disposition FROM law_catalog.citation_revisions WHERE clause_id = 105").fetchone()
    assert rec["disposition"] == "reviewed-no-action"


def test_apply_skips_on_body_drift(catalog):
    _clause(catalog, 106, "依据《中华人民共和国合同法》签订。")
    _setup_resolution(catalog)
    plan = rem.plan_batch("r1-drift", db=catalog)
    # simulate concurrent edit between plan and apply
    catalog.execute("UPDATE clauses SET body = '已被人工改过，不再引用旧法。' WHERE id = 106")
    catalog.commit()
    out = rem.apply_batch(plan, db=catalog)
    assert out["applied"] == 0 and out["skipped_drift"] == 1
    rec = catalog.execute(
        "SELECT disposition FROM law_catalog.citation_revisions WHERE clause_id = 106").fetchone()
    assert rec["disposition"] == "skipped-review"


def test_rollback_restores_and_marks(catalog):
    _clause(catalog, 107, "依据《中华人民共和国合同法》签订。")
    _setup_resolution(catalog)
    plan = rem.plan_batch("r1-rb", db=catalog)
    rem.apply_batch(plan, db=catalog)
    assert "民法典" in catalog.execute("SELECT body FROM clauses WHERE id=107").fetchone()["body"]

    out = rem.rollback_batch("r1-rb", db=catalog)
    assert out["restored"] == 1
    row = catalog.execute("SELECT body FROM clauses WHERE id = 107").fetchone()
    assert "《中华人民共和国合同法》" in row["body"]
    rec = catalog.execute(
        "SELECT disposition FROM law_catalog.citation_revisions WHERE clause_id = 107").fetchone()
    assert rec["disposition"] == "rolled-back"


def test_verify_closed_loop(catalog):
    _clause(catalog, 108, "依据《中华人民共和国合同法》签订。")
    _clause(catalog, 109, "依照《广州市城市供水用水条例》执行。")
    _setup_resolution(catalog)
    before = rem.verify_batch(db=catalog)
    plan = rem.plan_batch("r1-loop", db=catalog)
    rem.apply_batch(plan, db=catalog)
    after = rem.verify_batch(db=catalog)
    assert after["audit"]["repealed"] == 1          # only the needs_human local case
    assert before["audit"]["repealed"] >= 2


def test_revisions_page_registered(app_client, catalog):
    """Route ordering regression: the revisions page must be reachable
    (an earlier append-after-include left it unregistered -> 404)."""
    _clause(catalog, 110, "依据《中华人民共和国合同法》签订。")
    _setup_resolution(catalog)
    plan = rem.plan_batch("r1-page", db=catalog)
    rem.apply_batch(plan, db=catalog)
    r = app_client.get("/law-catalog/revisions")
    assert r.status_code == 200
    assert "r1-page" in r.text
    r2 = app_client.get("/law-catalog/revisions", params={"batch": "r1-page"})
    assert r2.status_code == 200 and "applied" in r2.text
