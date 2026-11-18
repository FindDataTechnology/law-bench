"""Tests for the law_catalog replica, name resolution, and citation audit."""

from __future__ import annotations

import json

import pytest

from src.law_catalog import audit as lc_audit
from src.law_catalog import resolve as lc_resolve
from src.law_catalog import store as lc_store
from src.law_catalog.alias_seed import seed as seed_aliases

# --- helpers -----------------------------------------------------------------


def _import_catalog(seeded_db, laws: list[dict]) -> dict:
    return lc_store.import_catalog(laws, db=seeded_db)


def _law(law_id: int, title: str, status: str | None = "有效", **kw) -> dict:
    return {
        "id": law_id,
        "title": title,
        "category": kw.get("category", "core_law"),
        "publish": kw.get("publish", "2021-01-01 00:00:00"),
        # expiry = 施行日期 (NOT an expiry date) - the 1999 合同法 shape.
        "expiry": kw.get("expiry", "2021-01-01 00:00:00"),
        "status": status,
        "src_db": kw.get("src_db", "lawv2"),
        "content_status": kw.get("content_status", "ok"),
    }


def _clause(seeded_db, clause_id: int, law_refs: list[dict], body: str = "正文") -> int:
    seeded_db.execute(
        "INSERT INTO clauses (id, contract_type, tags, section, body, law_refs, "
        "body_hash, created_at, updated_at) "
        "OVERRIDING SYSTEM VALUE "
        "VALUES (%s, 'sale', %s, '当事人', %s, %s, %s, '2026-01-01', '2026-01-01')",
        (clause_id, json.dumps({"source": "base"}), body, json.dumps(law_refs), f"hash{clause_id}"),
    )
    seeded_db.commit()
    return clause_id


CATALOG = [
    _law(1, "中华人民共和国民法典"),
    _law(2, "中华人民共和国合同法", status="已废止"),
    _law(3, "全国法院民商事审判工作会议纪要", status="有效"),
    _law(4, "中华人民共和国电力法", status=None),
    _law(5, "最高人民法院关于审理买卖合同纠纷案件适用法律问题的解释"),
]


@pytest.fixture
def catalog(seeded_db):
    _import_catalog(seeded_db, CATALOG)
    return seeded_db


# --- normalization -----------------------------------------------------------


def test_normalize_name_aligns_with_dedup_key():
    from src.eval.legal_refs import _dedup_key

    for raw in ("中华人民共和国民法典", "民法典", "《民法典》", " 《民法典》 "):
        assert lc_resolve.normalize_name(raw) == "民法典"
    assert lc_resolve.normalize_name("中华人民共和国民法典") == _dedup_key(
        "中华人民共和国民法典"
    )


# --- import (idempotent full replace) ----------------------------------------


def test_import_is_full_replace(seeded_db):
    _import_catalog(seeded_db, [_law(1, "旧目录"), _law(99, "将被清除", status="已废止")])
    _import_catalog(seeded_db, CATALOG)
    snap = lc_store.catalog_snapshot(db=seeded_db)
    assert snap["rows"] == len(CATALOG)
    assert snap["max_id"] == 5
    assert lc_store.get_law(99, db=seeded_db) is None


def test_import_rejects_empty_and_bad_rows(seeded_db):
    with pytest.raises(ValueError):
        lc_store.import_catalog([], db=seeded_db)
    with pytest.raises(ValueError):
        lc_store.import_catalog([{"title": "no id"}], db=seeded_db)


def test_load_export_file_jsonl(seeded_db, tmp_path):
    p = tmp_path / "laws.jsonl"
    p.write_text(
        json.dumps({"id": 7, "title": "中华人民共和国旅游法", "status": "有效"}, ensure_ascii=False)
        + "\n"
        + json.dumps({"id": 8, "title": "《带书名号的法》"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    rows = lc_store.load_export_file(str(p))
    assert [r["id"] for r in rows] == [7, 8]
    assert rows[1]["title"] == "《带书名号的法》"  # verbatim; 《》 stripped at resolve time


# --- resolution ladder -------------------------------------------------------


def test_resolve_exact_strips_prefix(catalog):
    idx = lc_resolve.LawCatalogIndex(db=catalog)
    res = idx.resolve("中华人民共和国民法典")
    assert (res["law_id"], res["resolved_via"]) == (1, "exact")


def test_resolve_alias_seed(catalog):
    lc_store.upsert_alias("九民纪要", "全国法院民商事审判工作会议纪要", None, source="seed", db=catalog)
    idx = lc_resolve.LawCatalogIndex(db=catalog)
    res = idx.resolve("九民纪要")
    assert (res["law_id"], res["resolved_via"]) == (3, "alias")


def test_resolve_trigram_above_threshold(catalog):
    idx = lc_resolve.LawCatalogIndex(db=catalog)
    res = idx.resolve("最高人民法院关于审理买卖合同纠纷案件适用法律问题的解释（2020修正）")
    if lc_store.has_trgm(db=catalog):
        assert (res["law_id"], res["resolved_via"]) == (5, "trigram")
    else:  # degraded env: no pg_trgm → unresolved
        assert res["resolved_via"] == "unresolved"


def test_resolve_unresolved_and_non_match(catalog):
    idx = lc_resolve.LawCatalogIndex(db=catalog)
    assert idx.resolve("不存在的加缪法")["resolved_via"] == "unresolved"
    # deliberate non-match: still unresolved, but hidden from the queue
    lc_store.upsert_alias("不存在的加缪法", None, None, source="non_match", db=catalog)
    assert idx.resolve("不存在的加缪法")["resolved_via"] == "unresolved"
    names = [r["cited_name"] for r in lc_store.distinct_unresolved(db=catalog)]
    assert "不存在的加缪法" not in names


# --- expiry trap -------------------------------------------------------------


def test_expiry_is_never_a_repeal_signal():
    # 1999 合同法 shape: expiry(=施行日期) long past, yet the law was current
    # until 2021. Past expiry + 有效 must be 'ok', never repealed.
    assert lc_audit.classify("有效", "exact") == "ok"
    assert lc_audit.classify("已废止", "exact") == "repealed"
    assert lc_audit.classify("失效", "alias") == "repealed"
    assert lc_audit.classify("已修改", "trigram") == "amended"
    assert lc_audit.classify(None, "exact") == "fallback"
    assert lc_audit.classify("sxx:3", "exact") == "fallback"
    assert lc_audit.classify(None, "unresolved") == "fallback"


def test_past_expiry_valid_law_classified_ok(catalog):
    # the catalog literally holds 合同法's publish/expiry shape for current laws
    _import_catalog(
        catalog,
        [_law(10, "中华人民共和国城乡规划法", publish="2007-10-28", expiry="2008-01-01", status="有效")],
    )
    idx = lc_resolve.LawCatalogIndex(db=catalog)
    res = idx.resolve("城乡规划法")
    assert lc_audit.classify(res["status"], res["resolved_via"]) == "ok"


# --- full resolve pass -------------------------------------------------------


def _refs(seeded_db, clause_id: int) -> list:
    return seeded_db.execute(
        "SELECT law_refs FROM clauses WHERE id = %s", (clause_id,)
    ).fetchone()["law_refs"]


def test_resolve_pass_writes_results_and_never_touches_law_refs(catalog):
    cid = _clause(
        catalog,
        501,
        [
            {"name": "中华人民共和国民法典", "category": "core_law", "category_zh": "核心法律"},
            {"name": "中华人民共和国合同法", "category": "core_law", "category_zh": "核心法律"},
            {"name": "不存在的加缪法", "category": "other", "category_zh": "其他"},
        ],
    )
    before = json.dumps(_refs(catalog, cid), ensure_ascii=False, sort_keys=True)

    stats = lc_resolve.resolve_all_clauses(db=catalog)
    assert stats["citations"] == 3
    assert stats["resolved"]["exact"] == 2

    rows = {r["cited_name"]: r for r in lc_store.list_resolutions(db=catalog)}
    assert rows["中华人民共和国民法典"]["law_id"] == 1
    assert rows["中华人民共和国合同法"]["law_status"] == "已废止"
    assert rows["不存在的加缪法"]["resolved_via"] == "unresolved"

    # derived column untouched (byte-identical)
    after = json.dumps(_refs(catalog, cid), ensure_ascii=False, sort_keys=True)
    assert before == after


def test_resolve_pass_rerun_follows_edit_and_prunes(catalog):
    cid = _clause(catalog, 502, [{"name": "中华人民共和国民法典", "category": "core_law", "category_zh": "核心法律"}])
    lc_resolve.resolve_all_clauses(db=catalog)
    assert len(lc_store.list_resolutions(db=catalog)) == 1

    # operator edits the clause: law_refs re-derived to a different citation
    catalog.execute(
        "UPDATE clauses SET law_refs = %s, body = '新正文', body_hash = 'hash502b' WHERE id = %s",
        (json.dumps([{"name": "中华人民共和国合同法", "category": "core_law", "category_zh": "核心法律"}]), cid),
    )
    catalog.commit()
    lc_resolve.resolve_all_clauses(db=catalog)

    rows = lc_store.list_resolutions(db=catalog)
    assert len(rows) == 1
    assert (rows[0]["cited_name"], rows[0]["law_id"], rows[0]["law_status"]) == (
        "中华人民共和国合同法", 2, "已废止",
    )

    # clause deleted → its resolution rows go too
    catalog.execute("DELETE FROM clauses WHERE id = %s", (cid,))
    catalog.commit()
    lc_resolve.resolve_all_clauses(db=catalog)
    assert lc_store.list_resolutions(db=catalog) == []


def test_review_confirmed_alias_used_by_next_pass(catalog):
    _clause(catalog, 503, [{"name": "九民纪要", "category": "other", "category_zh": "其他"}])
    lc_resolve.resolve_all_clauses(db=catalog)
    assert lc_store.list_resolutions(db=catalog)[0]["resolved_via"] == "unresolved"
    assert len(lc_store.distinct_unresolved(db=catalog)) == 1

    # operator confirms via the review queue → alias source='review'
    lc_store.upsert_alias(
        "九民纪要", "全国法院民商事审判工作会议纪要", None, source="review", db=catalog
    )
    lc_resolve.resolve_all_clauses(db=catalog)
    row = lc_store.list_resolutions(db=catalog)[0]
    assert (row["resolved_via"], row["law_id"]) == ("alias", 3)
    assert lc_store.distinct_unresolved(db=catalog) == []


# --- alias seeds -------------------------------------------------------------


def test_seed_aliases_insert_once_and_skip_curated(catalog):
    lc_store.upsert_alias("九民纪要", "自定义目标", None, source="manual", db=catalog)
    added = seed_aliases(db=catalog)
    assert added >= 1  # seeds landed...
    row = [r for r in lc_store.list_aliases(db=catalog).values() if r["alias"] == "九民纪要"][0]
    assert row["source"] == "manual"  # ...but the curated row won
    assert seed_aliases(db=catalog) == 0  # idempotent


# --- audit collection + report ----------------------------------------------


@pytest.fixture
def audited(catalog):
    _clause(catalog, 601, [
        {"name": "中华人民共和国合同法", "category": "core_law", "category_zh": "核心法律"},
        {"name": "不存在的加缪法", "category": "other", "category_zh": "其他"},
    ])
    _clause(catalog, 602, [{"name": "中华人民共和国电力法", "category": "core_law", "category_zh": "核心法律"}])
    lc_resolve.resolve_all_clauses(db=catalog)
    return lc_audit.collect_audit(db=catalog)


def test_audit_categories(audited):
    assert audited["summary"]["repealed"] == 1
    assert audited["summary"]["fallback"] == 2  # unresolved + NULL status
    assert audited["summary"]["ok"] == 0
    repealed = audited["findings"]["repealed"][0]
    assert (repealed["clause_id"], repealed["law_id"]) == (601, 2)


def test_report_is_deterministic(audited, catalog):
    a = lc_audit.render_report(audited)
    # fresh collection over the same DB state renders identically
    b = lc_audit.render_report(lc_audit.collect_audit(db=catalog))
    assert a == b
    assert "| 引用已废法律 | 1 |" in a


def test_write_report(tmp_path, audited):
    out = tmp_path / "report.md"
    lc_audit.write_report(audited, str(out))
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# 条款引法审计报告")
    assert "《中华人民共和国合同法》" in text


# --- web pages ---------------------------------------------------------------


def test_audit_page(app_client, audited):
    r = app_client.get("/law-catalog/audit")
    assert r.status_code == 200
    assert "引用已废法律" in r.text
    assert "《中华人民共和国合同法》" in r.text


def test_review_page_lists_unresolved(app_client, audited):
    r = app_client.get("/law-catalog/review")
    assert r.status_code == 200
    assert "不存在的加缪法" in r.text


def test_review_confirm_alias_flow(app_client, audited, seeded_db):
    r = app_client.post(
        "/law-catalog/review/alias",
        data={"alias": "不存在的加缪法", "law_id": "3"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    row = [r for r in lc_store.list_aliases(db=seeded_db).values() if r["alias"] == "不存在的加缪法"][0]
    assert (row["law_id"], row["source"]) == (3, "review")
    # queue no longer offers it (resolved next pass; and it left unresolved set)
    lc_resolve.resolve_all_clauses(db=seeded_db)
    assert "不存在的加缪法" not in [x["cited_name"] for x in lc_store.distinct_unresolved(db=seeded_db)]


def test_review_non_match_flow(app_client, audited, seeded_db):
    r = app_client.post(
        "/law-catalog/review/non-match",
        data={"alias": "不存在的加缪法"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    names = [r["cited_name"] for r in lc_store.distinct_unresolved(db=seeded_db)]
    assert "不存在的加缪法" not in names
    # page shows it under 已标记不匹配
    page = app_client.get("/law-catalog/review")
    assert "已标记不匹配" in page.text


def test_classify_vocabulary_2026_09_26():
    # export vocabulary after status normalization: 有效/已修改/已废止/未知/
    # 尚未生效/失效/已失效
    assert lc_audit.classify("已失效", "exact") == "repealed"
    assert lc_audit.classify("未知", "exact") == "fallback"
    assert lc_audit.classify("有效", "exact") == "ok"
    assert lc_audit.classify("尚未生效", "trigram") == "ok"


def test_non_match_suppresses_prefixed_citation(catalog):
    # aliases are stored normalized (中华人民共和国 stripped); a full-form
    # citation must still be suppressed from the review queue
    _clause(catalog, 703, [{"name": "中华人民共和国经济合同法", "category": "other", "category_zh": "其他"}])
    lc_resolve.resolve_all_clauses(db=catalog)
    assert len(lc_store.distinct_unresolved(db=catalog)) == 1
    lc_store.upsert_alias("中华人民共和国经济合同法", None, None, source="non_match", db=catalog)
    assert lc_store.distinct_unresolved(db=catalog) == []
